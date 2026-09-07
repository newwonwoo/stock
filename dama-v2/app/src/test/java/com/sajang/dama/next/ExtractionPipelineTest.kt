package com.sajang.dama.next

import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
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

    @Test
    fun mvpCandidatePrefersMuxedDirectVideo() {
        val selected = selectMvpDownloadCandidate(
            listOf(
                MediaDescriptor(
                    sourceUrl = "https://cdn.example.com/video-only.mp4",
                    kind = MediaKind.DIRECT,
                    trackRole = TrackRole.VIDEO_ONLY,
                    height = 1080
                ),
                MediaDescriptor(
                    sourceUrl = "https://cdn.example.com/muxed.mp4",
                    kind = MediaKind.DIRECT,
                    trackRole = TrackRole.MUXED,
                    height = 720
                ),
                MediaDescriptor(
                    sourceUrl = "https://cdn.example.com/master.m3u8",
                    kind = MediaKind.HLS,
                    trackRole = TrackRole.MUXED,
                    height = 2160
                )
            )
        )

        assertEquals("https://cdn.example.com/muxed.mp4", selected?.sourceUrl)
    }

    @Test
    fun mvpCandidateUsesHlsWhenDirectVideoIsUnavailable() {
        val selected = selectMvpDownloadCandidate(
            listOf(
                MediaDescriptor(
                    sourceUrl = "https://cdn.example.com/protected.mp4",
                    kind = MediaKind.DIRECT,
                    drmProtected = true
                ),
                MediaDescriptor(
                    sourceUrl = "https://cdn.example.com/master.m3u8",
                    kind = MediaKind.HLS,
                    trackRole = TrackRole.MUXED,
                    pageUrl = "https://example.com/watch/123"
                )
            )
        )

        assertEquals("https://cdn.example.com/master.m3u8", selected?.sourceUrl)
        assertEquals("https://example.com/watch/123", selected?.pageUrl)
    }

    @Test
    fun displayNameUsesSafeMp4Extension() {
        val name = buildDisplayName(
            title = "잘못된:/영상*이름",
            mimeType = "video/mp4",
            sourceUrl = "https://cdn.example.com/file",
            contentDisposition = null
        )

        assertTrue(name.endsWith(".mp4"))
        assertFalse(name.contains('/'))
        assertFalse(name.contains(':'))
        assertFalse(name.contains('*'))
    }

    @Test
    fun ytDlp403IsClassifiedExplicitly() {
        val detail = classifyYtDlpFailure(
            IllegalStateException("ERROR: HTTP Error 403: Forbidden")
        )

        assertEquals(FailureCode.HTTP_FORBIDDEN, detail.code)
        assertTrue(detail.retryable)
    }

    @Test
    fun ytDlpLoginMessageIsNotUnknown() {
        val detail = classifyYtDlpFailure(
            IllegalStateException("Sign in to confirm your age")
        )

        assertEquals(FailureCode.LOGIN_REQUIRED, detail.code)
    }

    @Test
    fun ytDlpConnectionResetHasDedicatedFailureCode() {
        val detail = classifyYtDlpFailure(
            IllegalStateException(
                "Unable to download webpage: [Errno 104] Connection reset by peer"
            )
        )

        assertEquals(FailureCode.NETWORK_RESET, detail.code)
        assertTrue(detail.retryable)
    }

    @Test
    fun browserOnlyFragmentIsRemovedBeforeYtDlpTransport() {
        val cleaned = stripFragmentForExtraction(
            "https://example.com/watch/123#mobile-watch-next"
        )

        assertEquals("https://example.com/watch/123", cleaned)
    }

    @Test
    fun connectionResetRetriesExactlyOnceWithIpv4() = runTest {
        val attempts = mutableListOf<Boolean>()

        val result = executeWithSingleIpv4Retry { forceIpv4 ->
            attempts += forceIpv4
            if (!forceIpv4) {
                throw IllegalStateException("[Errno 104] Connection reset by peer")
            }
            "recovered"
        }

        assertEquals("recovered", result)
        assertEquals(listOf(false, true), attempts)
    }

    @Test
    fun nonResetFailureIsNotRetried() = runTest {
        val attempts = mutableListOf<Boolean>()

        val error = runCatching {
            executeWithSingleIpv4Retry<String> { forceIpv4 ->
                attempts += forceIpv4
                throw IllegalStateException("HTTP Error 403: Forbidden")
            }
        }.exceptionOrNull()

        assertNotNull(error)
        assertEquals(listOf(false), attempts)
        assertEquals(FailureCode.HTTP_FORBIDDEN, classifyYtDlpFailure(error!!).code)
    }

    @Test
    fun repeatedResetStopsAfterTwoAttempts() = runTest {
        val attempts = mutableListOf<Boolean>()

        val error = runCatching {
            executeWithSingleIpv4Retry<String> { forceIpv4 ->
                attempts += forceIpv4
                throw IllegalStateException("Connection reset by peer")
            }
        }.exceptionOrNull()

        assertNotNull(error)
        assertEquals(listOf(false, true), attempts)
        assertEquals(FailureCode.NETWORK_RESET, classifyYtDlpFailure(error!!).code)
    }

    @Test
    fun networkResetIsEligibleForBrowserFallback() {
        val decision = decideBrowserFallback(
            FailureDetail(
                stage = PipelineStage.EXTRACTING,
                code = FailureCode.NETWORK_RESET,
                message = "reset"
            )
        )

        assertTrue(decision.eligible)
        assertEquals(BrowserFallbackReason.TRANSPORT_RESET, decision.reason)
    }

    @Test
    fun rateLimitDoesNotTriggerMoreBrowserTraffic() {
        val decision = decideBrowserFallback(
            FailureDetail(
                stage = PipelineStage.EXTRACTING,
                code = FailureCode.RATE_LIMITED,
                message = "wait"
            )
        )

        assertFalse(decision.eligible)
    }

    @Test
    fun diagnosticUrlRemovesQueryFragmentAndCredentials() {
        val sanitized = sanitizeUrlForDiagnostics(
            "https://name:password@example.com:8443/watch/123?token=secret#player"
        )

        assertEquals("https://example.com:8443/watch/123", sanitized)
    }

    @Test
    fun diagnosticReportDoesNotContainSecrets() {
        val session = DiagnosticSession(
            sessionId = "test-session",
            startedAtMillis = 0L
        )
        session.record(
            category = "FAILURE",
            message = "https://example.com/watch?id=1&token=secret",
            detail = "Cookie: session=private Authorization: Bearer-private"
        )

        val report = session.render()
        assertFalse(report.contains("secret"))
        assertFalse(report.contains("session=private"))
        assertFalse(report.contains("Bearer-private"))
        assertTrue(report.contains("https://example.com/watch"))
    }
}
