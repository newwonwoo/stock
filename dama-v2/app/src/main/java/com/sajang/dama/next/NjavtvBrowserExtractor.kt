package com.sajang.dama.next

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.graphics.Color
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.coroutines.resume

/**
 * Narrow browser-session extractor for NjavTV.
 *
 * The page initializes an HLS player inside the browser session while plain HTTP
 * clients are rejected. This extractor observes the public page's own media
 * request, captures only the request URL/headers/cookies, and immediately tears
 * the WebView down. It does not intercept response bytes or bypass encryption.
 */
class NjavtvBrowserExtractor(
    private val context: Context
) : MediaExtractor {
    override val id: String = "njavtv-browser"

    override suspend fun extract(
        input: String,
        reporter: StageReporter
    ): ExtractionResult {
        val host = runCatching { Uri.parse(input).host.orEmpty() }.getOrDefault("")
            .lowercase(Locale.US)
        if (host != "njavtv.com" && !host.endsWith(".njavtv.com")) {
            return ExtractionResult.Unsupported(id, "not an NjavTV URL")
        }

        val activity = context.findActivity()
            ?: return ExtractionResult.Failure(
                FailureDetail(
                    stage = PipelineStage.EXTRACTING,
                    code = FailureCode.EXTRACTOR_FAILED,
                    message = "브라우저 감지 화면을 만들 수 없습니다.",
                    technicalDetail = "Activity context is unavailable"
                )
            )

        reporter.report(PipelineStage.INITIALIZING_ENGINE)
        return withContext(Dispatchers.Main.immediate) {
            detectHlsRequest(activity, input, reporter)
        }
    }

    private suspend fun detectHlsRequest(
        activity: Activity,
        pageUrl: String,
        reporter: StageReporter
    ): ExtractionResult = suspendCancellableCoroutine { continuation ->
        val completed = AtomicBoolean(false)
        val mainHandler = Handler(Looper.getMainLooper())
        val container = FrameLayout(activity).apply {
            setBackgroundColor(Color.TRANSPARENT)
            alpha = 0.01f
            translationX = -10_000f
            translationY = -10_000f
        }
        val webView = WebView(activity)
        container.addView(
            webView,
            FrameLayout.LayoutParams(2, 2)
        )
        activity.addContentView(
            container,
            ViewGroup.LayoutParams(2, 2)
        )

        fun cleanup() {
            mainHandler.removeCallbacksAndMessages(container)
            runCatching { webView.stopLoading() }
            runCatching {
                webView.loadUrl("about:blank")
                webView.clearHistory()
                webView.removeAllViews()
                webView.destroy()
            }
            runCatching { (container.parent as? ViewGroup)?.removeView(container) }
        }

        fun finish(result: ExtractionResult) {
            if (!completed.compareAndSet(false, true)) return
            mainHandler.post {
                cleanup()
                if (continuation.isActive) continuation.resume(result)
            }
        }

        fun capture(request: WebResourceRequest) {
            val mediaUrl = request.url.toString()
            if (!looksLikeHls(mediaUrl)) return

            val safeHeaders = request.requestHeaders
                .filterKeys { name ->
                    name.equals("Accept", ignoreCase = true) ||
                        name.equals("Accept-Language", ignoreCase = true) ||
                        name.equals("Origin", ignoreCase = true) ||
                        name.equals("Referer", ignoreCase = true) ||
                        name.equals("User-Agent", ignoreCase = true)
                }
                .toMutableMap()
                .apply {
                    putIfAbsent("Referer", pageUrl)
                    putIfAbsent("User-Agent", webView.settings.userAgentString)
                }
            val cookies = CookieManager.getInstance().getCookie(mediaUrl)
                ?: CookieManager.getInstance().getCookie(pageUrl)

            reporter.report(PipelineStage.PARSING_FORMATS)
            finish(
                ExtractionResult.Success(
                    extractorId = id,
                    media = listOf(
                        MediaDescriptor(
                            sourceUrl = mediaUrl,
                            manifestUrl = mediaUrl,
                            kind = MediaKind.HLS,
                            title = titleFrom(pageUrl),
                            qualityLabel = "HLS",
                            trackRole = TrackRole.MUXED,
                            mimeType = "application/vnd.apple.mpegurl",
                            headers = safeHeaders,
                            cookies = cookies
                        )
                    )
                )
            )
        }

        continuation.invokeOnCancellation {
            if (completed.compareAndSet(false, true)) {
                mainHandler.post { cleanup() }
            }
        }

        val timeout = Runnable {
            finish(
                ExtractionResult.Failure(
                    FailureDetail(
                        stage = PipelineStage.EXTRACTING,
                        code = FailureCode.MEDIA_REQUEST_NOT_FOUND,
                        message = "브라우저에서 HLS 요청을 찾지 못했습니다.",
                        technicalDetail = "NjavTV browser observation timed out after 60 seconds",
                        retryable = true
                    )
                )
            )
        }

        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            mediaPlaybackRequiresUserGesture = false
            mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW
            loadsImagesAutomatically = true
        }
        CookieManager.getInstance().apply {
            setAcceptCookie(true)
            setAcceptThirdPartyCookies(webView, true)
        }
        webView.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(
                view: WebView?,
                request: WebResourceRequest
            ): android.webkit.WebResourceResponse? {
                capture(request)
                return null
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                if (completed.get()) return
                reporter.report(PipelineStage.EXTRACTING)
                // Some player builds create the request only after play() is invoked.
                mainHandler.postDelayed({
                    if (!completed.get()) {
                        webView.evaluateJavascript(
                            """
                            (() => {
                              document.querySelectorAll('video').forEach(video => {
                                video.muted = true;
                                video.playsInline = true;
                                const play = video.play();
                                if (play && play.catch) play.catch(() => {});
                              });
                              return true;
                            })()
                            """.trimIndent(),
                            null
                        )
                    }
                }, 3_000)
            }

            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?
            ) {
                super.onReceivedError(view, request, error)
                if (request?.isForMainFrame == true && !completed.get()) {
                    finish(
                        ExtractionResult.Failure(
                            FailureDetail(
                                stage = PipelineStage.EXTRACTING,
                                code = FailureCode.EXTRACTOR_FAILED,
                                message = "브라우저 페이지를 열지 못했습니다.",
                                technicalDetail = "${error?.errorCode}: ${error?.description}",
                                retryable = true
                            )
                        )
                    )
                }
            }
        }

        mainHandler.postAtTime(timeout, container, android.os.SystemClock.uptimeMillis() + 60_000)
        webView.loadUrl(pageUrl)
    }
}

internal fun looksLikeHls(url: String): Boolean {
    val normalized = url.lowercase(Locale.US)
    return normalized.contains(".m3u8") ||
        normalized.contains("manifest.m3u") ||
        normalized.contains("master.m3u")
}

private fun titleFrom(url: String): String =
    Uri.parse(url).lastPathSegment
        ?.replace('-', ' ')
        ?.trim()
        ?.takeIf { it.isNotBlank() }
        ?: "NjavTV 영상"

private tailrec fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}
