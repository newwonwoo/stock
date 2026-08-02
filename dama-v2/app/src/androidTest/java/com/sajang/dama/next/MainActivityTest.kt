package com.sajang.dama.next

import android.provider.MediaStore
import androidx.compose.ui.test.assertExists
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextClearance
import androidx.compose.ui.test.performTextInput
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MainActivityTest {
    @get:Rule
    val composeRule = createAndroidComposeRule<MainActivity>()

    @Test
    fun directMp4IsDownloadedAndSavedToMediaStore() {
        analyze("http://10.0.2.2:8765/media/sample.mp4")

        waitForStatus("추출 성공")
        composeRule.onNodeWithTag("downloadButton")
            .assertIsDisplayed()
            .performClick()

        waitForStatus("저장 완료", timeoutMillis = 60_000)
        assertTrue(hasSavedDamaVideo())
    }

    @Test
    fun controlledFixturePageIsExtractedByAndroidYtDlp() {
        analyze("http://10.0.2.2:8765/page/direct")

        waitForStatus("추출 성공", timeoutMillis = 120_000)
        composeRule.onNodeWithTag("statusTitle")
            .assertTextContains("yt-dlp", substring = true)
        composeRule.onNodeWithTag("downloadButton").assertIsDisplayed()
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
                composeRule.onNodeWithText(expected, substring = true)
                    .assertExists()
                true
            }.getOrDefault(false)
        }
    }

    private fun hasSavedDamaVideo(): Boolean {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val projection = arrayOf(
            MediaStore.Video.Media._ID,
            MediaStore.Video.Media.SIZE,
            MediaStore.Video.Media.RELATIVE_PATH
        )
        context.contentResolver.query(
            MediaStore.Video.Media.EXTERNAL_CONTENT_URI,
            projection,
            "${MediaStore.Video.Media.RELATIVE_PATH} LIKE ? AND ${MediaStore.Video.Media.SIZE} > 0",
            arrayOf("Movies/담아%"),
            "${MediaStore.Video.Media.DATE_ADDED} DESC"
        )?.use { cursor ->
            return cursor.moveToFirst()
        }
        return false
    }
}
