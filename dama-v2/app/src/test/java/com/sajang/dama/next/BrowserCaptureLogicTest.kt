package com.sajang.dama.next

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BrowserCaptureLogicTest {
    @Test
    fun targetDomainsUseBrowserCaptureDirectly() {
        assertTrue(
            BrowserCaptureContract.shouldUseBrowserCapture(
                "https://mypikpak.com/s/share-id/file-id"
            )
        )
        assertTrue(
            BrowserCaptureContract.shouldUseBrowserCapture(
                "https://njavtv.com/dm44/ko/sample"
            )
        )
        assertFalse(
            BrowserCaptureContract.shouldUseBrowserCapture(
                "https://www.pornhub.com/view_video.php?viewkey=abc"
            )
        )
    }

    @Test
    fun pikpakDownloadLinkRanksAboveGenericMediaUrl() {
        val pikpak = browserCandidateScore(
            url = "https://dl-a.mypikpak.com/download/file?token=x",
            source = "json",
            sourceKey = "$.file_info.web_content_link"
        )
        val generic = browserCandidateScore(
            url = "https://cdn.example.com/video.mp4",
            source = "performance"
        )

        assertTrue(pikpak > generic)
    }

    @Test
    fun njavtvHlsRanksAboveUnrelatedDirectAsset() {
        val hls = browserCandidateScore(
            url = "https://media.surrit.com/path/master.m3u8?token=x",
            source = "window.hls"
        )
        val generic = browserCandidateScore(
            url = "https://cdn.example.com/trailer.mp4",
            source = "performance"
        )

        assertTrue(hls > generic)
    }
}
