package com.sajang.dama.next

import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ExtractionPipelineTest {
    private val pipeline = ExtractionPipeline(listOf(DirectUrlExtractor()))

    @Test
    fun directMp4ProducesDescriptor() = runTest {
        val result = pipeline.resolve("https://cdn.example.com/video/sample.mp4?token=abc")

        assertTrue(result is ExtractionResult.Success)
        val media = (result as ExtractionResult.Success).media.single()
        assertEquals(MediaKind.DIRECT, media.kind)
        assertEquals("video/mp4", media.mimeType)
    }

    @Test
    fun sharedTextExtractsHlsUrlAndDropsTrailingPunctuation() = runTest {
        val result = pipeline.resolve(
            "이 영상을 확인하세요: https://cdn.example.com/live/master.m3u8)."
        )

        assertTrue(result is ExtractionResult.Success)
        val media = (result as ExtractionResult.Success).media.single()
        assertEquals(MediaKind.HLS, media.kind)
        assertEquals("https://cdn.example.com/live/master.m3u8", media.sourceUrl)
    }

    @Test
    fun ordinaryWebPageReturnsExplicitUnsupportedFailure() = runTest {
        val result = pipeline.resolve("https://example.com/watch/123")

        assertTrue(result is ExtractionResult.Failure)
        val detail = (result as ExtractionResult.Failure).detail
        assertEquals(FailureCode.EXTRACTOR_UNSUPPORTED, detail.code)
        assertEquals(PipelineStage.EXTRACTING, detail.stage)
    }
}
