package com.sajang.dama.next

import android.content.Context
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import com.yausername.youtubedl_android.mapper.VideoFormat
import com.yausername.youtubedl_android.mapper.VideoInfo
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.URI
import java.util.Locale

class YtDlpExtractor(
    context: Context
) : MediaExtractor {
    override val id: String = "yt-dlp"

    private val appContext = context.applicationContext

    override suspend fun extract(
        input: String,
        reporter: StageReporter
    ): ExtractionResult = withContext(Dispatchers.IO) {
        try {
            reporter.report(PipelineStage.INITIALIZING_ENGINE)
            YtDlpRuntime.ensureReady(appContext)

            val extractionUrl = stripFragmentForExtraction(input)
            if (shouldRefreshExtractor(extractionUrl)) {
                YtDlpRuntime.updateIfDue(appContext)
            }

            reporter.report(PipelineStage.EXTRACTING)
            val info = executeWithSingleIpv4Retry { forceIpv4 ->
                YoutubeDL.getInstance().getInfo(
                    buildRequest(extractionUrl, forceIpv4)
                )
            }

            reporter.report(PipelineStage.PARSING_FORMATS)
            val descriptors = mapVideoInfo(info, extractionUrl)
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

    private fun buildRequest(
        input: String,
        forceIpv4: Boolean
    ): YoutubeDLRequest = YoutubeDLRequest(input).apply {
        addOption("--no-playlist")
        addOption("--socket-timeout", "12")
        addOption("--retries", "0")
        addOption("--extractor-retries", "0")
        addOption("--no-warnings")
        applyYtDlpSiteProfile(input)
        if (forceIpv4) addOption("-4")
    }
}

internal data class YtDlpSiteProfile(
    val userAgent: String,
    val headers: Map<String, String>
)

internal fun ytDlpSiteProfile(input: String): YtDlpSiteProfile {
    val host = runCatching { URI(input).host.orEmpty() }
        .getOrDefault("")
        .lowercase(Locale.US)
    val pornhub = host == "pornhub.com" || host.endsWith(".pornhub.com")

    return if (pornhub) {
        YtDlpSiteProfile(
            userAgent = DESKTOP_CHROME_USER_AGENT,
            headers = linkedMapOf(
                "Accept-Language" to "en-US,en;q=0.9",
                "Cookie" to PORNHUB_AGE_COOKIES
            )
        )
    } else {
        YtDlpSiteProfile(
            userAgent = ANDROID_CHROME_USER_AGENT,
            headers = mapOf(
                "Accept-Language" to "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
            )
        )
    }
}

internal fun YoutubeDLRequest.applyYtDlpSiteProfile(input: String) {
    val profile = ytDlpSiteProfile(input)
    addOption("--user-agent", profile.userAgent)
    profile.headers.forEach { (name, value) ->
        addOption("--add-header", "$name:$value")
    }
}

internal const val ANDROID_CHROME_USER_AGENT =
    "Mozilla/5.0 (Linux; Android 14; SM-S918N) AppleWebKit/537.36 " +
        "(KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36"

internal const val DESKTOP_CHROME_USER_AGENT =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
        "AppleWebKit/537.36 (KHTML, like Gecko) " +
        "Chrome/138.0.0.0 Safari/537.36"

internal const val PORNHUB_AGE_COOKIES =
    "age_verified=1; accessAgeDisclaimerPH=1; " +
        "accessAgeDisclaimerUK=1; accessPH=1; platform=pc"

internal fun shouldRefreshExtractor(url: String): Boolean {
    val host = runCatching { URI(url).host }
        .getOrNull()
        ?.lowercase(Locale.US)
        ?: return false
    return host !in setOf("localhost", "127.0.0.1", "10.0.2.2") &&
        !host.endsWith(".local")
}

private class YtDlpRetryException(
    firstError: Throwable,
    secondError: Throwable
) : RuntimeException(
    buildString {
        append("default attempt: ")
        append(firstError.message.orEmpty().take(900))
        append(" | IPv4 retry: ")
        append(secondError.message.orEmpty().take(900))
    },
    secondError
)

internal suspend fun <T> executeWithSingleIpv4Retry(
    execute: suspend (forceIpv4: Boolean) -> T
): T {
    return try {
        execute(false)
    } catch (firstError: Throwable) {
        if (!isConnectionReset(firstError)) throw firstError

        try {
            execute(true)
        } catch (secondError: Throwable) {
            throw YtDlpRetryException(firstError, secondError)
        }
    }
}

internal fun stripFragmentForExtraction(input: String): String =
    input.substringBefore('#').ifBlank { input }

internal fun isConnectionReset(error: Throwable): Boolean {
    var current: Throwable? = error
    repeat(8) {
        val text = current?.message.orEmpty().lowercase(Locale.US)
        if (
            "connection reset" in text ||
            "errno 104" in text ||
            "reset by peer" in text
        ) {
            return true
        }
        current = current?.cause
    }
    return false
}

internal fun mapVideoInfo(
    info: VideoInfo,
    pageUrl: String? = null
): List<MediaDescriptor> {
    val title = info.title ?: info.fulltitle ?: "영상"
    val fallbackHeaders = info.httpHeaders.orEmpty()

    val mappedFormats = info.formats.orEmpty()
        .mapNotNull { format ->
            format.toDescriptor(
                title = title,
                fallbackHeaders = fallbackHeaders,
                pageUrl = pageUrl
            )
        }
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
            pageUrl = pageUrl,
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
    fallbackHeaders: Map<String, String>,
    pageUrl: String?
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
        pageUrl = pageUrl,
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
        isConnectionReset(error) -> FailureCode.NETWORK_RESET
        "unsupported url" in normalized -> FailureCode.EXTRACTOR_UNSUPPORTED
        "sign in" in normalized || "login" in normalized -> FailureCode.LOGIN_REQUIRED
        "cookie" in normalized -> FailureCode.COOKIE_REQUIRED
        "http error 403" in normalized || "forbidden" in normalized -> FailureCode.HTTP_FORBIDDEN
        "http error 429" in normalized || "too many requests" in normalized -> FailureCode.RATE_LIMITED
        else -> FailureCode.EXTRACTOR_FAILED
    }

    val retryable = code in setOf(
        FailureCode.EXTRACTOR_FAILED,
        FailureCode.NETWORK_RESET,
        FailureCode.HTTP_FORBIDDEN,
        FailureCode.RATE_LIMITED
    )

    return FailureDetail(
        stage = PipelineStage.EXTRACTING,
        code = code,
        message = when (code) {
            FailureCode.EXTRACTOR_UNSUPPORTED -> "yt-dlp가 이 주소를 지원하지 않습니다."
            FailureCode.NETWORK_RESET ->
                "일반 요청과 IPv4 재시도 모두 상대 서버에서 연결이 종료됐습니다."
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
