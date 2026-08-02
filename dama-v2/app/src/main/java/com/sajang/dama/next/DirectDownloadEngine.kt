package com.sajang.dama.next

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.provider.MediaStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL
import java.util.Locale

class DirectDownloadEngine(
    context: Context
) : DownloadEngine {
    override val id: String = "direct-http"

    private val appContext = context.applicationContext
    private val streamDownloader by lazy { YtDlpDownloadEngine(appContext) }

    override suspend fun download(media: MediaDescriptor): Result<String> {
        if (media.kind != MediaKind.DIRECT || media.pageUrl != null) {
            return streamDownloader.download(media)
        }

        return withContext(Dispatchers.IO) {
            runCatching {
                require(!media.drmProtected) {
                    "DRM-protected media cannot be downloaded"
                }

                val connection = (URL(media.sourceUrl).openConnection() as HttpURLConnection).apply {
                    instanceFollowRedirects = true
                    connectTimeout = 15_000
                    readTimeout = 30_000
                    requestMethod = "GET"
                    setRequestProperty("Accept", "*/*")
                    media.headers.forEach { (name, value) ->
                        if (name.isNotBlank() && value.isNotBlank()) {
                            setRequestProperty(name, value)
                        }
                    }
                    media.cookies?.takeIf { it.isNotBlank() }?.let {
                        setRequestProperty("Cookie", it)
                    }
                }

                var pendingUri: Uri? = null
                try {
                    connection.connect()
                    val responseCode = connection.responseCode
                    if (responseCode !in 200..299) {
                        error("HTTP $responseCode ${connection.responseMessage.orEmpty()}".trim())
                    }

                    val mimeType = connection.contentType
                        ?.substringBefore(';')
                        ?.trim()
                        ?.takeIf { it.isNotBlank() }
                        ?: media.mimeType
                        ?: inferMimeType(media.sourceUrl)
                        ?: "video/mp4"

                    val displayName = buildDisplayName(
                        title = media.title,
                        mimeType = mimeType,
                        sourceUrl = media.sourceUrl,
                        contentDisposition = connection.getHeaderField("Content-Disposition")
                    )

                    val values = ContentValues().apply {
                        put(MediaStore.Video.Media.DISPLAY_NAME, displayName)
                        put(MediaStore.Video.Media.MIME_TYPE, mimeType)
                        put(MediaStore.Video.Media.RELATIVE_PATH, "Movies/담아")
                        put(MediaStore.Video.Media.IS_PENDING, 1)
                    }

                    val resolver = appContext.contentResolver
                    pendingUri = resolver.insert(
                        MediaStore.Video.Media.EXTERNAL_CONTENT_URI,
                        values
                    ) ?: error("MediaStore insert returned null")

                    resolver.openOutputStream(pendingUri, "w")?.use { output ->
                        connection.inputStream.use { input ->
                            input.copyTo(output, DEFAULT_BUFFER_SIZE)
                        }
                    } ?: error("Unable to open MediaStore output stream")

                    val completed = ContentValues().apply {
                        put(MediaStore.Video.Media.IS_PENDING, 0)
                    }
                    resolver.update(pendingUri, completed, null, null)
                    pendingUri.toString()
                } catch (error: Throwable) {
                    pendingUri?.let { uri ->
                        runCatching { appContext.contentResolver.delete(uri, null, null) }
                    }
                    throw error
                } finally {
                    connection.disconnect()
                }
            }
        }
    }
}

internal fun selectMvpDownloadCandidate(media: List<MediaDescriptor>): MediaDescriptor? {
    return media
        .asSequence()
        .filter { !it.drmProtected && it.trackRole != TrackRole.AUDIO_ONLY }
        .sortedWith(
            compareByDescending<MediaDescriptor> { it.trackRole == TrackRole.MUXED }
                .thenByDescending { it.height ?: 0 }
                .thenByDescending { it.kind == MediaKind.DIRECT }
                .thenByDescending { it.fileSizeBytes ?: 0L }
        )
        .firstOrNull()
}

internal fun buildDisplayName(
    title: String,
    mimeType: String?,
    sourceUrl: String,
    contentDisposition: String?
): String {
    val dispositionName = contentDisposition
        ?.substringAfter("filename=", missingDelimiterValue = "")
        ?.trim()
        ?.trim('"', '\'')
        ?.takeIf { it.isNotBlank() }

    if (dispositionName != null) {
        return sanitizeFileName(dispositionName)
    }

    val extension = extensionFor(mimeType, sourceUrl)
    val base = sanitizeFileName(title)
        .ifBlank { "영상" }
        .take(80)
    return "${base}_${System.currentTimeMillis()}$extension"
}

private fun sanitizeFileName(value: String): String = value
    .replace(Regex("[\\/:*?\"<>|\\p{Cntrl}]"), "_")
    .trim()
    .trim('.')

private fun extensionFor(mimeType: String?, sourceUrl: String): String {
    val normalizedMime = mimeType.orEmpty().lowercase(Locale.US)
    return when {
        "video/mp4" in normalizedMime -> ".mp4"
        "video/webm" in normalizedMime -> ".webm"
        "video/quicktime" in normalizedMime -> ".mov"
        "audio/mp4" in normalizedMime -> ".m4a"
        "audio/mpeg" in normalizedMime -> ".mp3"
        else -> {
            val pathExtension = sourceUrl
                .substringBefore('?')
                .substringBefore('#')
                .substringAfterLast('.', missingDelimiterValue = "")
                .lowercase(Locale.US)
                .takeIf { it.matches(Regex("[a-z0-9]{2,5}")) }
            pathExtension?.let { ".$it" } ?: ".mp4"
        }
    }
}

private fun inferMimeType(sourceUrl: String): String? {
    val path = sourceUrl.substringBefore('?').lowercase(Locale.US)
    return when {
        path.endsWith(".mp4") || path.endsWith(".m4v") -> "video/mp4"
        path.endsWith(".webm") -> "video/webm"
        path.endsWith(".mov") -> "video/quicktime"
        path.endsWith(".m4a") -> "audio/mp4"
        path.endsWith(".mp3") -> "audio/mpeg"
        else -> null
    }
}
