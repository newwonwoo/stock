package com.sajang.dama.next

import android.app.Activity
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class BrowserCaptureActivityTest {
    @Test
    fun capturesDirectLinkFromLocalJsonFixture() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val intent = BrowserCaptureContract.createIntent(
            context,
            "http://10.0.2.2:8765/page/browser-json"
        )
        ActivityScenario.launchActivityForResult<BrowserCaptureActivity>(intent).use { scenario ->
            val result = scenario.result
            assertEquals(Activity.RESULT_OK, result.resultCode)
            val descriptor = BrowserCaptureContract.toDescriptor(result.resultData)
            assertNotNull(descriptor)
            assertEquals(MediaKind.DIRECT, descriptor?.kind)
        }
    }

    @Test
    fun capturesHlsLinkFromLocalWindowFixture() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val intent = BrowserCaptureContract.createIntent(
            context,
            "http://10.0.2.2:8765/page/browser-hls"
        )
        ActivityScenario.launchActivityForResult<BrowserCaptureActivity>(intent).use { scenario ->
            val result = scenario.result
            assertEquals(Activity.RESULT_OK, result.resultCode)
            val descriptor = BrowserCaptureContract.toDescriptor(result.resultData)
            assertNotNull(descriptor)
            assertEquals(MediaKind.HLS, descriptor?.kind)
        }
    }
}
