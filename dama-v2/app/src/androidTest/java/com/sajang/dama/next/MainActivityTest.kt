package com.sajang.dama.next

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextClearance
import androidx.compose.ui.test.performTextInput
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MainActivityTest {
    @get:Rule
    val composeRule = createAndroidComposeRule<MainActivity>()

    @Test
    fun directMp4CompletesWithoutNetworkOrBrowser() {
        analyze("https://cdn.example.com/video/sample.mp4?token=secret")

        waitForStatus("추출 성공")
        composeRule.onNodeWithTag("shareDiagnosticsButton").assertIsDisplayed()
    }

    @Test
    fun controlledFixturePageIsExtractedByAndroidYtDlp() {
        analyze("http://10.0.2.2:8765/page/direct")

        waitForStatus("추출 성공", timeoutMillis = 120_000)
        composeRule.onNodeWithTag("statusTitle")
            .assertTextContains("yt-dlp", substring = true)
        composeRule.onNodeWithTag("shareDiagnosticsButton").assertIsDisplayed()
    }

    @Test
    fun invalidInputProducesFailureAndDiagnosticFile() {
        analyze("not-a-url")

        waitForStatus("분석 실패")
        composeRule.onNodeWithTag("shareDiagnosticsButton").assertIsDisplayed()
    }

    private fun analyze(url: String) {
        composeRule.onNodeWithTag("urlInput").performTextClearance()
        composeRule.onNodeWithTag("urlInput").performTextInput(url)
        composeRule.onNodeWithTag("analyzeButton").performClick()
    }

    private fun waitForStatus(
        expected: String,
        timeoutMillis: Long = 20_000
    ) {
        composeRule.waitUntil(timeoutMillis) {
            runCatching {
                composeRule.onNodeWithTag("statusTitle")
                    .assertTextContains(expected, substring = true)
                true
            }.getOrDefault(false)
        }
    }
}
