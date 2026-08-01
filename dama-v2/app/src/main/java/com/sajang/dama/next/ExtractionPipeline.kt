package com.sajang.dama.next

import java.net.URI
import java.util.Locale

class ExtractionPipeline(
    private val extractors: List<MediaExtractor>
) {
    suspend fun resolve(
        input: String,
        reporter: StageReporter = StageReporter { }
    ): ExtractionResult {
        reporter.report(PipelineStage.VALIDATING_URL)
        val normalized = normalizeHttpUrl(input)
            ?: return ExtractionResult.Failure(
                FailureDetail(
                    stage = PipelineStage.VALIDATING_URL,
                    code = FailureCode.INVALID_URL,
                    message = "올바른 http 또는 https 주소가 아닙니다.",
                    technicalDetail = input.take(300)
                )
            )

        reporter.report(PipelineStage.EXTRACTING)
        val unsupportedReasons = mutableListOf<String>()

        for (extractor in extractors) {
            when (val result = extractor.extract(normalized)) {
                is ExtractionResult.Success -> {
                    if (result.media.isEmpty()) {
                        unsupportedReasons += "${extractor.id}: empty result"
                        continue
                    }
                    reporter.report(PipelineStage.FORMATS_FOUND)
                    return result
                }

                is ExtractionResult.Unsupported -> {
                    unsupportedReasons += "${result.extractorId}: ${result.reason}"
                }

                is ExtractionResult.Failure -> {
                    reporter.report(PipelineStage.FAILED)
                    return result
                }
            }
        }

        reporter.report(PipelineStage.FAILED)
        return ExtractionResult.Failure(
            FailureDetail(
                stage = PipelineStage.EXTRACTING,
                code = FailureCode.EXTRACTOR_UNSUPPORTED,
                message = "현재 연결된 추출기가 이 주소를 처리하지 못했습니다.",
                technicalDetail = unsupportedReasons.joinToString(" | ").take(1_000),
                retryable = false
            )
        )
    }
}

class DirectUrlExtractor : MediaExtractor {
    override val id: String = "direct-url"

    override suspend fun extract(input: String): ExtractionResult {
        val uri = runCatching { URI(input) }.getOrNull()
            ?: return ExtractionResult.Unsupported(id, "URI parse failed")
        val path = uri.path.orEmpty().lowercase(Locale.US)
        val kind = when {
            path.endsWith(".m3u8") -> MediaKind.HLS
            path.endsWith(".mpd") -> MediaKind.DASH
            DIRECT_EXTENSIONS.any(path::endsWith) -> MediaKind.DIRECT
            else -> null
        } ?: return ExtractionResult.Unsupported(id, "not a direct media URL")

        val mimeType = when (kind) {
            MediaKind.HLS -> "application/vnd.apple.mpegurl"
            MediaKind.DASH -> "application/dash+xml"
            MediaKind.DIRECT -> mimeFor(path)
        }

        return ExtractionResult.Success(
            extractorId = id,
            media = listOf(
                MediaDescriptor(
                    sourceUrl = input,
                    kind = kind,
                    title = fileNameFrom(path),
                    mimeType = mimeType
                )
            )
        )
    }

    private fun fileNameFrom(path: String): String =
        path.substringAfterLast('/').substringBeforeLast('.').ifBlank { "영상" }

    private fun mimeFor(path: String): String = when {
        path.endsWith(".webm") -> "video/webm"
        path.endsWith(".mov") -> "video/quicktime"
        else -> "video/mp4"
    }

    private companion object {
        val DIRECT_EXTENSIONS = listOf(".mp4", ".webm", ".mov", ".m4v")
    }
}

internal fun normalizeHttpUrl(input: String): String? {
    val candidate = HTTP_URL.find(input.trim())?.value ?: return null
    val uri = runCatching { URI(candidate) }.getOrNull() ?: return null
    if (uri.scheme?.lowercase(Locale.US) !in setOf("http", "https")) return null
    if (uri.host.isNullOrBlank()) return null
    return candidate.trimEnd('.', ',', ')', ']', '}', '>', '\"', '\'')
}

private val HTTP_URL = Regex("https?://\\S+", RegexOption.IGNORE_CASE)
