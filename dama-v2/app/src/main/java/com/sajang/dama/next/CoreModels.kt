package com.sajang.dama.next

enum class PipelineStage {
    IDLE,
    VALIDATING_URL,
    EXTRACTING,
    FORMATS_FOUND,
    READY_TO_DOWNLOAD,
    FAILED
}

enum class FailureCode {
    INVALID_URL,
    EXTRACTOR_UNSUPPORTED,
    EXTRACTOR_FAILED,
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

data class MediaDescriptor(
    val sourceUrl: String,
    val kind: MediaKind,
    val title: String = "영상",
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

    suspend fun extract(input: String): ExtractionResult
}

interface DownloadEngine {
    val id: String

    suspend fun download(media: MediaDescriptor): Result<String>
}
