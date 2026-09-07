package com.sajang.dama.next

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class YtDlpSiteProfileTest {
    @Test
    fun pornhubUsesDesktopChromeAndOrdinaryAgeConfirmationCookies() {
        val profile = ytDlpSiteProfile(
            "https://www.pornhub.com/view_video.php?viewkey=sample"
        )

        assertEquals(DESKTOP_CHROME_USER_AGENT, profile.userAgent)
        assertTrue(profile.headers.getValue("Cookie").contains("age_verified=1"))
        assertTrue(profile.headers.getValue("Cookie").contains("platform=pc"))
        assertEquals("en-US,en;q=0.9", profile.headers["Accept-Language"])
    }

    @Test
    fun unrelatedSitesKeepAndroidChromeProfileWithoutInjectedCookies() {
        val profile = ytDlpSiteProfile("https://example.com/video")

        assertEquals(ANDROID_CHROME_USER_AGENT, profile.userAgent)
        assertFalse(profile.headers.containsKey("Cookie"))
        assertTrue(profile.headers.getValue("Accept-Language").startsWith("ko-KR"))
    }

    @Test
    fun similarlyNamedHostDoesNotReceivePornhubProfile() {
        val profile = ytDlpSiteProfile("https://pornhub.com.example.org/video")

        assertEquals(ANDROID_CHROME_USER_AGENT, profile.userAgent)
        assertFalse(profile.headers.containsKey("Cookie"))
    }
}
