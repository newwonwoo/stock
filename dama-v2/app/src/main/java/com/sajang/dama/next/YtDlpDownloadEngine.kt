package com.sajang.dama.next

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.provider.MediaStore
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.util.Locale
import java.util.UUID

class MvpDownloadEngine(
    context: Context
) : DownloadEngine {
    override val id: String = "mvp-download"

    private val direct = DirectDownloadEngine(context)
    private val ytDlp = YtDlpDownloadEngine(context)

    override suspend fun download(media: MediaDescriptor): Result<String> {
        return if (media.kind == MediaKind.DIRECT && media.pageUrl == null) {
            direct.download(media)
        } else {
            ytDlp.download(media)
        }
    }
}

class YtDlpDownloadEngine(
    context: Context
) : DownloadEngine {
    override val id: String = "yt-dlp-ffmpeg"

    private val appContext = context.applicationContext

    override suspend fun download(media: MediaDescriptor): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            require(!media.drmProtected) {
                "DRM-protected media cannot be downloaded"
            }

            YtDlpRuntime.ensureReady(appContext)
            val workDir = File(
                appContext.cacheDir,
                "yt-dlp-downloads/${UUID.randomUUID()}"
            ).apply { mkdirs() }

            try {
                val input = media.pageUrl ?: media.sourceUrl
                val outputTemplate = File(workDir, "download.%(ext)s").absolutePath
                val request = YoutubeDLRequest(input).apply {
                    addOption("--no-playlist")
                    addOption("--socket-timeout", "20")
                    addOption("--retries", "3")
                    addOption("--fragment-retries", "3")
                    addOption("--no-mtime")
                    addOption("--merge-output-format", "mp4")
                    addOption("--remux-video", "mp4")
                    addOption("--output", outputTemplate)

                    formatExpression(media)?.let { expression ->
                        addOption("--format", expression)
                    }

                    media.headers.forEach { (name, value) ->
                        if (name.isNotBlank() && value.isNotBlank()) {
                            addOption("--add-header", "$name:$value")
                        }
                    }
                    media.cookies?.takeIf { it.isNotBlank() }?.let { cookies ->
                        addOption("--add-header", "Cookie:$cookies")
                    }
                }

                YoutubeDL.getInstance().execute(request)
                val output = workDir.walkTopDown()
                    .filter { file ->
                        file.isFile &&
                            file.length() > 0L &&
                            !file.name.endsWith(".part") &&
                            !file.name.endsWith(".ytdl") &&
                            !file.name.endsWith(".json")
                    }
                    .maxByOrNull(File::length)
                    ?: error("yt-dlp completed without a media file")

                saveToMediaStore(output, media.title)
            } finally {
                workDir.deleteRecursively()
            }
        }
    }

    private fun formatExpression(media: MediaDescriptor): String? {
        val formatId = media.formatId?.takeIf { it.isNotBlank() }
        if (media.pageUrl == null) return formatId

        return when (media.trackRole) {
            TrackRole.MUXED -> formatId
            TrackRole.VIDEO_ONLY -> formatId?.let { "$it+bestaudio/best" }
                ?: "bestvideo+bestaudio/best"
            TrackRole.AUDIO_ONLY -> "bestvideo+$formatId/best"
            TrackRole.UNKNOWN -> formatId ?: "bestvideo+bestaudio/best"
        }
    }

    private fun saveToMediaStore(file: File, title: String): String {
        val mimeType = mimeTypeFor(file)
        val displayName = buildDisplayName(
            title = title,
            mimeType = mimeType,
            sourceUrl = file.name,
            contentDisposition = null
        )
        val values = ContentValues().apply {
            put(MediaStore.Video.Media.DISPLAY_NAME, displayName)
            put(MediaStore.Video.Media.MIME_TYPE, mimeType)
            put(MediaStore.Video.Media.RELATIVE_PATH, "Movies/담아")
            put(MediaStore.Video.Media.IS_PENDING, 1)
        }

        val resolver = appContext.contentResolver
        var pendingUri: Uri? = null
        try {
            pendingUri = resolver.insert(
                MediaStore.Video.Media.EXTERNAL_CONTENT_URI,
                values
            ) ?: error("MediaStore insert returned null")

            resolver.openOutputStream(pendingUri, "w")?.use { output ->
                file.inputStream().use { input ->
                    input.copyTo(output, DEFAULT_BUFFER_SIZE)
                }
            } ?: error("Unable to open MediaStore output stream")

            val completed = ContentValues().apply {
                put(MediaStore.Video.Media.IS_PENDING, 0)
            }
            resolver.update(pendingUri, completed, null, null)
            return pendingUri.toString()
        } catch (error: Throwable) {
            pendingUri?.let { uri ->
                runCatching { resolver.delete(uri, null, null) }
            }
            throw error
        }
    }

    private fun mimeTypeFor(file: File): String {
        return when (file.extension.lowercase(Locale.US)) {
            "mp4", "m4v" -> "video/mp4"
            "webm" -> "video/webm"
            "mov" -> "video/quicktime"
            "mkv" -> "video/x-matroska"
            "ts", "m2ts" -> "video/mp2t"
            else -> "video/mp4"
        }
    }
}
