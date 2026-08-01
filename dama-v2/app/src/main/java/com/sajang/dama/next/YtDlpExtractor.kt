package com.sajang.dama.next

import android.content.Context
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import com.yausername.youtubedl_android.mapper.VideoFormat
import com.yausername.youtubedl_android.mapper.VideoInfo
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.util.Locale

class YtDlpExtractor(
    context: Context
) : MediaExtractor {
    override val id: String = "yt-dlp"

    private val appContext = context.applicationContext
    private val initMutex = Mutex()

    @Volatile
    private var initialized = false

    override suspend fun extract(
        input: String,
        reporter: StageReporter
    ): ExtractionResult = withContext(Dispatchers.IO) {
        try {
            reporter.report(PipelineStage.INITIALIZING_ENGINE)
            ensureInitialized()

            reporter.report(PipelineStage.EXTRACTING)
            val request = YoutubeDLRequest(input).apply {
                addOption("--no-playlist")
                addOption("--socket-timeout", "10")
                addOption("--retries", "1")
                addOption("--no-warnings")
            }
            val info = YoutubeDL.getInstance().getInfo(request)

            reporter.report(PipelineStage.PARSING_FORMATS)
            val descriptors = mapVideoInfo(info)
            if (descriptors.isEmpty()) {
                ExtractionResult.Unsupported(
                    extractorId = id,
                    reason = "yt-dlp returned no downloadable format"
                )
            } else {
                ExtractionResult.Success(
                    extractorId = id,
                    media = descriptors
                )
            }
        } catch (error: Throwable) {
            ExtractionResult.Failure(classifyYtDlpFailure(error))
        }
    }

    private suspend fun ensureInitialized() {
        if (initialized) return
        initMutex.withLock {
            if (initialized) return
            YoutubeDL.getInstance().init(appContext)
            initialized = true
        }
    }
}

internal fun mapVideoInfo(info: VideoInfo): List<MediaDescriptor> {
    val title = info.title ?: info.fulltitle ?: "영상"
    val fallbackHeaders = info.httpHeaders.orEmpty()

    val mappedFormats = info.formats.orEmpty()
        .mapNotNull { format -> format.toDescriptor(title, fallbackHeaders) }
        .distinctBy { descriptor ->
            listOf(
                descriptor.formatId.orEmpty(),
                descriptor.sourceUrl,
                descriptor.trackRole.name
            ).joinToString("|")
        }

    if (mappedFormats.isNotEmpty()) return mappedFormats

    val fallbackUrl = info.url ?: info.manifestUrl ?: return emptyList()
    return listOf(
        MediaDescriptor(
            sourceUrl = fallbackUrl,
            manifestUrl = info.manifestUrl,
            kind = inferKind(info.manifestUrl ?: fallbackUrl, info.ext),
            title = title,
            formatId = info.formatId,
            qualityLabel = info.resolution ?: info.format,
            trackRole = TrackRole.MUXED,
            width = info.width.takeIf { it > 0 },
            height = info.height.takeIf { it > 0 },
            fileSizeBytes = positiveSize(info.fileSize, info.fileSizeApproximate),
            mimeType = inferMimeType(info.ext, info.manifestUrl ?: fallbackUrl),
            headers = fallbackHeaders
        )
    )
}

private fun VideoFormat.toDescriptor(
    title: String,
    fallbackHeaders: Map<String, String>
): MediaDescriptor? {
    val resolvedUrl = url ?: manifestUrl ?: return null
    val videoPresent = !vcodec.isNullOrBlank() && vcodec != "none"
    val audioPresent = !acodec.isNullOrBlank() && acodec != "none"
    val role = when {
        videoPresent && audioPresent -> TrackRole.MUXED
        videoPresent -> TrackRole.VIDEO_ONLY
        audioPresent -> TrackRole.AUDIO_ONLY
        else -> TrackRole.UNKNOWN
    }
    val label = formatNote
        ?: height.takeIf { it > 0 }?.let { "${it}p" }
        ?: format
        ?: formatId

    return MediaDescriptor(
        sourceUrl = resolvedUrl,
        manifestUrl = manifestUrl,
        kind = inferKind(manifestUrl ?: resolvedUrl, ext),
        title = title,
        formatId = formatId,
        qualityLabel = label,
        trackRole = role,
        width = width.takeIf { it > 0 },
        height = height.takeIf { it > 0 },
        videoCodec = vcodec,
        audioCodec = acodec,
        fileSizeBytes = positiveSize(fileSize, fileSizeApproximate),
        mimeType = inferMimeType(ext, manifestUrl ?: resolvedUrl),
        headers = httpHeaders ?: fallbackHeaders
    )
}

internal fun classifyYtDlpFailure(error: Throwable): FailureDetail {
    val technical = buildString {
        append(error::class.java.simpleName)
        error.message?.takeIf { it.isNotBlank() }?.let {
            append(": ")
            append(it)
        }
    }.take(2_000)
    val normalized = technical.lowercase(Locale.US)

    val code = when {
        "unsupported url" in normalized -> FailureCode.EXTRACTOR_UNSUPPORTED
        "sign in" in normalized || "login" in normalized -> FailureCode.LOGIN_REQUIRED
        "cookie" in normalized -> FailureCode.COOKIE_REQUIRED
        "http error 403" in normalized || "forbidden" in normalized -> FailureCode.HTTP_FORBIDDEN
        "http error 429" in normalized || "too many requests" in normalized -> FailureCode.RATE_LIMITED
        else -> FailureCode.EXTRACTOR_FAILED
    }

    val retryable = code in setOf(
        FailureCode.EXTRACTOR_FAILED,
        FailureCode.HTTP_FORBIDDEN,
        FailureCode.RATE_LIMITED
    )

    return FailureDetail(
        stage = PipelineStage.EXTRACTING,
        code = code,
        message = when (code) {
            FailureCode.EXTRACTOR_UNSUPPORTED -> "yt-dlp가 이 주소를 지원하지 않습니다."
            FailureCode.LOGIN_REQUIRED -> "로그인이 필요한 페이지입니다."
            FailureCode.COOKIE_REQUIRED -> "브라우저 쿠키가 필요한 페이지입니다."
            FailureCode.HTTP_FORBIDDEN -> "사이트가 추출 요청을 거부했습니다."
            FailureCode.RATE_LIMITED -> "사이트 요청 제한에 걸렸습니다."
            else -> "yt-dlp 추출 중 오류가 발생했습니다."
        },
        technicalDetail = technical,
        retryable = retryable
    )
}

private fun inferKind(url: String, ext: String?): MediaKind {
    val signal = "$url ${ext.orEmpty()}".lowercase(Locale.US)
    return when {
        ".m3u8" in signal || "m3u8" == ext?.lowercase(Locale.US) -> MediaKind.HLS
        ".mpd" in signal || "dash" == ext?.lowercase(Locale.US) -> MediaKind.DASH
        else -> MediaKind.DIRECT
    }
}

private fun inferMimeType(ext: String?, url: String): String? {
    return when {
        url.contains(".m3u8", ignoreCase = true) -> "application/vnd.apple.mpegurl"
        url.contains(".mpd", ignoreCase = true) -> "application/dash+xml"
        ext.equals("mp4", ignoreCase = true) || ext.equals("m4v", ignoreCase = true) -> "video/mp4"
        ext.equals("webm", ignoreCase = true) -> "video/webm"
        ext.equals("mov", ignoreCase = true) -> "video/quicktime"
        ext.equals("m4a", ignoreCase = true) -> "audio/mp4"
        ext.equals("mp3", ignoreCase = true) -> "audio/mpeg"
        else -> null
    }
}

private fun positiveSize(exact: Long, approximate: Long): Long? = when {
    exact > 0 -> exact
    approximate > 0 -> approximate
    else -> null
}
