package com.sajang.dama.next

enum class PipelineStage {
    IDLE,
    VALIDATING_URL,
    INITIALIZING_ENGINE,
    EXTRACTING,
    PARSING_FORMATS,
    FORMATS_FOUND,
    READY_TO_DOWNLOAD,
    FAILED
}

enum class FailureCode {
    INVALID_URL,
    EXTRACTOR_UNSUPPORTED,
    EXTRACTOR_FAILED,
    NETWORK_RESET,
    COOKIE_REQUIRED,
    LOGIN_REQUIRED,
    HTTP_FORBIDDEN,
    RATE_LIMITED,
    MEDIA_REQUEST_NOT_FOUND,
    DRM_DETECTED,
    URL_EXPIRED,
    DOWNLOAD_FAILED,
    STORAGE_FULL,
    MUX_FAILED
}

data class FailureDetail(
    val stage: PipelineStage,
    val code: FailureCode,
    val message: String,
    val technicalDetail: String? = null,
    val retryable: Boolean = false
)

enum class MediaKind {
    DIRECT,
    HLS,
    DASH
}

enum class TrackRole {
    MUXED,
    VIDEO_ONLY,
    AUDIO_ONLY,
    UNKNOWN
}

data class MediaDescriptor(
    val sourceUrl: String,
    val kind: MediaKind,
    val title: String = "영상",
    val pageUrl: String? = null,
    val formatId: String? = null,
    val qualityLabel: String? = null,
    val trackRole: TrackRole = TrackRole.UNKNOWN,
    val manifestUrl: String? = null,
    val width: Int? = null,
    val height: Int? = null,
    val videoCodec: String? = null,
    val audioCodec: String? = null,
    val fileSizeBytes: Long? = null,
    val mimeType: String? = null,
    val headers: Map<String, String> = emptyMap(),
    val cookies: String? = null,
    val expiresAtEpochMillis: Long? = null,
    val drmProtected: Boolean = false
)

sealed interface ExtractionResult {
    data class Success(
        val extractorId: String,
        val media: List<MediaDescriptor>
    ) : ExtractionResult

    data class Unsupported(
        val extractorId: String,
        val reason: String
    ) : ExtractionResult

    data class Failure(
        val detail: FailureDetail
    ) : ExtractionResult
}

fun interface StageReporter {
    fun report(stage: PipelineStage)
}

interface MediaExtractor {
    val id: String

    suspend fun extract(
        input: String,
        reporter: StageReporter = StageReporter { }
    ): ExtractionResult
}

interface DownloadEngine {
    val id: String

    suspend fun download(media: MediaDescriptor): Result<String>
}
