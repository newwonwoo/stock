package com.sajang.dama.next

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.core.view.setPadding
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import java.net.URI
import java.util.Locale
import java.util.concurrent.ConcurrentHashMap

object BrowserCaptureContract {
    private const val EXTRA_PAGE_URL = "browser_page_url"
    private const val EXTRA_MEDIA_URL = "browser_media_url"
    private const val EXTRA_MEDIA_KIND = "browser_media_kind"
    private const val EXTRA_MEDIA_TITLE = "browser_media_title"
    private const val EXTRA_HEADERS = "browser_media_headers"
    private const val EXTRA_COOKIES = "browser_media_cookies"
    const val EXTRA_ERROR = "browser_capture_error"

    fun createIntent(context: Context, pageUrl: String): Intent =
        Intent(context, BrowserCaptureActivity::class.java)
            .putExtra(EXTRA_PAGE_URL, pageUrl)

    fun shouldUseBrowserCapture(input: String): Boolean {
        val normalized = normalizeHttpUrl(input) ?: return false
        val host = runCatching { URI(normalized).host }
            .getOrNull()
            ?.lowercase(Locale.US)
            ?: return false
        return host == "mypikpak.com" ||
            host.endsWith(".mypikpak.com") ||
            host == "njavtv.com" ||
            host.endsWith(".njavtv.com") ||
            host == "njav.tv" ||
            host.endsWith(".njav.tv")
    }

    fun toDescriptor(data: Intent?): MediaDescriptor? {
        val sourceUrl = data?.getStringExtra(EXTRA_MEDIA_URL)?.takeIf { it.isNotBlank() }
            ?: return null
        val kind = runCatching {
            MediaKind.valueOf(data.getStringExtra(EXTRA_MEDIA_KIND).orEmpty())
        }.getOrDefault(kindFromUrl(sourceUrl))
        val title = data.getStringExtra(EXTRA_MEDIA_TITLE)
            ?.takeIf { it.isNotBlank() }
            ?: "영상"
        val headers = parseHeaders(data.getStringExtra(EXTRA_HEADERS))
        val cookies = data.getStringExtra(EXTRA_COOKIES)?.takeIf { it.isNotBlank() }

        return MediaDescriptor(
            sourceUrl = sourceUrl,
            manifestUrl = sourceUrl.takeIf { kind != MediaKind.DIRECT },
            kind = kind,
            title = title,
            pageUrl = null,
            trackRole = TrackRole.MUXED,
            mimeType = when (kind) {
                MediaKind.DIRECT -> inferBrowserMime(sourceUrl)
                MediaKind.HLS -> "application/vnd.apple.mpegurl"
                MediaKind.DASH -> "application/dash+xml"
            },
            headers = headers,
            cookies = cookies
        )
    }

    internal fun resultIntent(
        pageUrl: String,
        sourceUrl: String,
        kind: MediaKind,
        title: String,
        headers: Map<String, String>,
        cookies: String?
    ): Intent = Intent()
        .putExtra(EXTRA_PAGE_URL, pageUrl)
        .putExtra(EXTRA_MEDIA_URL, sourceUrl)
        .putExtra(EXTRA_MEDIA_KIND, kind.name)
        .putExtra(EXTRA_MEDIA_TITLE, title)
        .putExtra(EXTRA_HEADERS, JSONObject(headers).toString())
        .putExtra(EXTRA_COOKIES, cookies)

    private fun parseHeaders(value: String?): Map<String, String> {
        if (value.isNullOrBlank()) return emptyMap()
        return runCatching {
            val json = JSONObject(value)
            buildMap {
                json.keys().forEach { key ->
                    val headerValue = json.optString(key)
                    if (key.isNotBlank() && headerValue.isNotBlank()) {
                        put(key, headerValue)
                    }
                }
            }
        }.getOrDefault(emptyMap())
    }
}

internal data class BrowserMediaLink(
    val url: String,
    val sourceKey: String
)

internal fun extractBrowserMediaLinks(body: String): List<BrowserMediaLink> {
    if (body.isBlank() || body.length > 2_500_000) return emptyList()
    val root = runCatching { JSONTokener(body).nextValue() }.getOrNull() ?: return emptyList()
    val results = mutableListOf<BrowserMediaLink>()

    fun walk(value: Any?, path: String, depth: Int) {
        if (depth > 18) return
        when (value) {
            is JSONObject -> value.keys().forEach { key ->
                val child = value.opt(key)
                val childPath = "$path.$key"
                if (child is String && isBrowserMediaUrl(child, childPath)) {
                    results += BrowserMediaLink(child, childPath)
                }
                walk(child, childPath, depth + 1)
            }

            is JSONArray -> for (index in 0 until value.length()) {
                walk(value.opt(index), "$path[$index]", depth + 1)
            }
        }
    }

    walk(root, "$", 0)
    return results.distinctBy(BrowserMediaLink::url)
}

internal fun browserCandidateScore(
    url: String,
    source: String,
    sourceKey: String = ""
): Int {
    val uri = runCatching { URI(url) }.getOrNull() ?: return Int.MIN_VALUE
    val host = uri.host.orEmpty().lowercase(Locale.US)
    val path = uri.path.orEmpty().lowercase(Locale.US)
    val key = sourceKey.lowercase(Locale.US)
    val kind = kindFromUrl(url)

    var score = when (kind) {
        MediaKind.DIRECT -> 130
        MediaKind.HLS -> 105
        MediaKind.DASH -> 100
    }
    if (host.startsWith("dl-") && host.endsWith(".mypikpak.com")) score += 420
    if (host.endsWith("surrit.com")) score += 250
    if ("/download/" in path) score += 260
    if ("web_content_link" in key || "webcontentlink" in key) score += 350
    if ("download_url" in key || "downloadurl" in key) score += 300
    if ("medias" in key && ".link" in key) score += 220
    if (source.startsWith("network")) score += 80
    if (source == "window.hls") score += 70
    if (source == "json") score += 60
    if (kind == MediaKind.HLS) score += path.count { it == '/' } * 4
    return score
}

private data class BrowserCandidate(
    val url: String,
    val kind: MediaKind,
    val source: String,
    val sourceKey: String,
    val headers: Map<String, String>,
    val score: Int,
    val observedAt: Long
)

class BrowserCaptureActivity : ComponentActivity() {
    private val handler = Handler(Looper.getMainLooper())
    private val requestHeaders = ConcurrentHashMap<String, Map<String, String>>()
    private val candidates = ConcurrentHashMap<String, BrowserCandidate>()

    private lateinit var pageUrl: String
    private lateinit var webView: WebView
    private lateinit var statusView: TextView
    private lateinit var progressBar: ProgressBar

    private var bestCandidate: BrowserCandidate? = null
    private var completed = false

    private val finishRunnable = Runnable { finishWithBestCandidate() }
    private val timeoutRunnable = Runnable {
        if (completed) return@Runnable
        completed = true
        setResult(
            Activity.RESULT_CANCELED,
            Intent().putExtra(
                BrowserCaptureContract.EXTRA_ERROR,
                "브라우저에서 다운로드 가능한 미디어 요청을 찾지 못했습니다."
            )
        )
        finish()
    }

    @SuppressLint("SetJavaScriptEnabled", "AddJavascriptInterface")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        pageUrl = intent.getStringExtra("browser_page_url")
            ?.let(::normalizeHttpUrl)
            ?: run {
                setResult(
                    Activity.RESULT_CANCELED,
                    Intent().putExtra(BrowserCaptureContract.EXTRA_ERROR, "올바른 페이지 주소가 아닙니다.")
                )
                finish()
                return
            }

        buildContentView()

        CookieManager.getInstance().apply {
            setAcceptCookie(true)
            setAcceptThirdPartyCookies(webView, true)
        }

        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            loadsImagesAutomatically = true
            mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
            mediaPlaybackRequiresUserGesture = false
            userAgentString = ANDROID_USER_AGENT
        }
        webView.addJavascriptInterface(CaptureBridge(), "DamaBridge")
        webView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                progressBar.progress = newProgress
            }
        }
        webView.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView?, url: String?, favicon: android.graphics.Bitmap?) {
                statusView.text = "페이지를 열고 있습니다."
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                statusView.text = "영상 요청을 감지하고 있습니다."
                view?.evaluateJavascript(CAPTURE_SCRIPT, null)
            }

            override fun shouldInterceptRequest(
                view: WebView?,
                request: WebResourceRequest?
            ): WebResourceResponse? {
                request ?: return null
                val url = request.url.toString()
                requestHeaders[url] = sanitizeRequestHeaders(request.requestHeaders)
                if (isBrowserMediaUrl(url, "network")) {
                    addCandidate(
                        url = url,
                        source = "network:${request.method.lowercase(Locale.US)}",
                        sourceKey = "",
                        headers = request.requestHeaders
                    )
                }
                return null
            }
        }

        if (WebViewFeature.isFeatureSupported("DOCUMENT_START_SCRIPT")) {
            WebViewCompat.addDocumentStartJavaScript(
                webView,
                CAPTURE_SCRIPT,
                setOf("*")
            )
        }

        handler.postDelayed(timeoutRunnable, MAX_CAPTURE_MILLIS)
        webView.loadUrl(pageUrl)
    }

    private fun buildContentView() {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.WHITE)
        }
        val statusBar = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(12))
            setBackgroundColor(Color.rgb(247, 247, 247))
        }
        statusView = TextView(this).apply {
            text = "브라우저 감지 준비 중"
            setTextColor(Color.DKGRAY)
            textSize = 15f
            gravity = Gravity.CENTER_VERTICAL
        }
        progressBar = ProgressBar(
            this,
            null,
            android.R.attr.progressBarStyleHorizontal
        ).apply {
            max = 100
            progress = 0
        }
        statusBar.addView(
            statusView,
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            )
        )
        statusBar.addView(
            progressBar,
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(3)
            ).apply { topMargin = dp(8) }
        )
        webView = WebView(this)
        root.addView(
            statusBar,
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            )
        )
        root.addView(
            webView,
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                0,
                1f
            )
        )
        setContentView(root)
    }

    private inner class CaptureBridge {
        @JavascriptInterface
        fun onCandidate(url: String?, source: String?) {
            if (url.isNullOrBlank()) return
            runOnUiThread {
                addCandidate(
                    url = url,
                    source = source.orEmpty().ifBlank { "javascript" },
                    sourceKey = "",
                    headers = requestHeaders[url].orEmpty()
                )
            }
        }

        @JavascriptInterface
        fun onJson(responseUrl: String?, body: String?) {
            if (body.isNullOrBlank()) return
            val links = extractBrowserMediaLinks(body)
            if (links.isEmpty()) return
            runOnUiThread {
                val headers = responseUrl
                    ?.let { requestHeaders[it] }
                    .orEmpty()
                links.forEach { link ->
                    addCandidate(
                        url = link.url,
                        source = "json",
                        sourceKey = link.sourceKey,
                        headers = headers
                    )
                }
            }
        }
    }

    private fun addCandidate(
        url: String,
        source: String,
        sourceKey: String,
        headers: Map<String, String>
    ) {
        if (completed || !isBrowserMediaUrl(url, sourceKey)) return
        if (looksLikeProtectedRequest(url)) return

        val kind = kindFromUrl(url)
        val candidate = BrowserCandidate(
            url = url,
            kind = kind,
            source = source,
            sourceKey = sourceKey,
            headers = sanitizeRequestHeaders(headers),
            score = browserCandidateScore(url, source, sourceKey),
            observedAt = System.currentTimeMillis()
        )
        candidates[url] = candidate
        val current = bestCandidate
        if (
            current == null ||
            candidate.score > current.score ||
            (candidate.score == current.score && candidate.observedAt > current.observedAt)
        ) {
            bestCandidate = candidate
            statusView.text = when (kind) {
                MediaKind.DIRECT -> "직접 영상 파일을 찾았습니다. 확인 중입니다."
                MediaKind.HLS -> "HLS 영상을 찾았습니다. 최종 재생목록 확인 중입니다."
                MediaKind.DASH -> "DASH 영상을 찾았습니다. 확인 중입니다."
            }
        }

        handler.removeCallbacks(finishRunnable)
        handler.postDelayed(
            finishRunnable,
            if (kind == MediaKind.DIRECT) 2_000L else 5_000L
        )
    }

    private fun finishWithBestCandidate() {
        if (completed) return
        val candidate = bestCandidate ?: return
        completed = true
        handler.removeCallbacks(timeoutRunnable)

        val headers = buildMap {
            putAll(candidate.headers)
            if (keys.none { it.equals("Referer", ignoreCase = true) }) {
                put("Referer", pageUrl)
            }
            if (keys.none { it.equals("User-Agent", ignoreCase = true) }) {
                put("User-Agent", webView.settings.userAgentString ?: ANDROID_USER_AGENT)
            }
        }
        val cookieManager = CookieManager.getInstance()
        val cookies = cookieManager.getCookie(candidate.url)
            ?: cookieManager.getCookie(pageUrl)
        val title = webView.title?.trim().orEmpty().ifBlank { "영상" }

        setResult(
            Activity.RESULT_OK,
            BrowserCaptureContract.resultIntent(
                pageUrl = pageUrl,
                sourceUrl = candidate.url,
                kind = candidate.kind,
                title = title,
                headers = headers,
                cookies = cookies
            )
        )
        finish()
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        if (::webView.isInitialized) {
            webView.apply {
                stopLoading()
                loadUrl("about:blank")
                removeJavascriptInterface("DamaBridge")
                clearHistory()
                (parent as? ViewGroup)?.removeView(this)
                destroy()
            }
        }
        super.onDestroy()
    }

    private fun dp(value: Int): Int =
        (value * resources.displayMetrics.density).toInt()

    private companion object {
        const val MAX_CAPTURE_MILLIS = 45_000L
        const val ANDROID_USER_AGENT =
            "Mozilla/5.0 (Linux; Android 14; SM-S918N) AppleWebKit/537.36 " +
                "(KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36"

        val CAPTURE_SCRIPT = """
            (() => {
              if (window.__DAMA_CAPTURE_INSTALLED__) return;
              window.__DAMA_CAPTURE_INSTALLED__ = true;
              const bridge = window.DamaBridge;
              if (!bridge) return;
              const send = (value, source) => {
                try {
                  const url = typeof value === 'string' ? value : String(value || '');
                  if (/^https?:\/\//i.test(url)) bridge.onCandidate(url, source || 'javascript');
                } catch (_) {}
              };
              const inspectBody = (url, text) => {
                try {
                  if (typeof text === 'string' && text.length > 0 && text.length <= 2500000) {
                    bridge.onJson(url || '', text);
                  }
                } catch (_) {}
              };

              const originalFetch = window.fetch;
              if (originalFetch) {
                window.fetch = async function(...args) {
                  const response = await originalFetch.apply(this, args);
                  try {
                    send(response.url, 'fetch');
                    const type = (response.headers.get('content-type') || '').toLowerCase();
                    if (type.includes('json') || response.url.includes('/drive/v1/share')) {
                      response.clone().text().then(text => inspectBody(response.url, text)).catch(() => {});
                    }
                  } catch (_) {}
                  return response;
                };
              }

              const originalOpen = XMLHttpRequest.prototype.open;
              const originalSend = XMLHttpRequest.prototype.send;
              XMLHttpRequest.prototype.open = function(method, url, ...rest) {
                this.__damaUrl = url;
                return originalOpen.call(this, method, url, ...rest);
              };
              XMLHttpRequest.prototype.send = function(...args) {
                this.addEventListener('load', function() {
                  try {
                    const url = this.responseURL || this.__damaUrl || '';
                    send(url, 'xhr');
                    const type = (this.getResponseHeader('content-type') || '').toLowerCase();
                    if ((type.includes('json') || String(url).includes('/drive/v1/share')) && typeof this.responseText === 'string') {
                      inspectBody(url, this.responseText);
                    }
                  } catch (_) {}
                });
                return originalSend.apply(this, args);
              };

              const scan = () => {
                try {
                  if (window.hls && window.hls.url) send(window.hls.url, 'window.hls');
                  document.querySelectorAll('video,audio,source').forEach(node => {
                    send(node.currentSrc || node.src || node.getAttribute('src'), 'dom-media');
                  });
                  performance.getEntriesByType('resource').forEach(entry => send(entry.name, 'performance'));
                } catch (_) {}
              };
              try {
                performance.setResourceTimingBufferSize(5000);
                new PerformanceObserver(list => {
                  list.getEntries().forEach(entry => send(entry.name, 'performance-observer'));
                }).observe({entryTypes: ['resource']});
              } catch (_) {}
              scan();
              setInterval(scan, 700);
            })();
        """.trimIndent()
    }
}

private fun sanitizeRequestHeaders(headers: Map<String, String>): Map<String, String> {
    val allowed = setOf(
        "accept",
        "accept-language",
        "origin",
        "referer",
        "user-agent"
    )
    return headers.filterKeys { it.lowercase(Locale.US) in allowed }
}

private fun isBrowserMediaUrl(value: String, sourceKey: String): Boolean {
    val uri = runCatching { URI(value) }.getOrNull() ?: return false
    if (uri.scheme?.lowercase(Locale.US) !in setOf("http", "https")) return false
    val host = uri.host.orEmpty().lowercase(Locale.US)
    val path = uri.path.orEmpty().lowercase(Locale.US)
    val key = sourceKey.lowercase(Locale.US)
    if (path.endsWith(".ts") || path.endsWith(".m4s")) return false
    if (looksLikeProtectedRequest(value)) return false

    return path.endsWith(".m3u8") ||
        path.endsWith(".mpd") ||
        path.endsWith(".mp4") ||
        path.endsWith(".webm") ||
        path.endsWith(".m4v") ||
        path.endsWith(".mov") ||
        (host.startsWith("dl-") && host.endsWith(".mypikpak.com") && "/download/" in path) ||
        "web_content_link" in key ||
        "webcontentlink" in key ||
        "download_url" in key ||
        "downloadurl" in key ||
        ("medias" in key && ".link" in key)
}

private fun looksLikeProtectedRequest(url: String): Boolean {
    val signal = url.lowercase(Locale.US)
    return "widevine" in signal ||
        "/license" in signal ||
        "drm" in signal ||
        "clearkey" in signal
}

private fun kindFromUrl(url: String): MediaKind {
    val path = runCatching { Uri.parse(url).path.orEmpty() }
        .getOrDefault("")
        .lowercase(Locale.US)
    return when {
        path.endsWith(".m3u8") -> MediaKind.HLS
        path.endsWith(".mpd") -> MediaKind.DASH
        else -> MediaKind.DIRECT
    }
}

private fun inferBrowserMime(url: String): String? {
    val path = runCatching { Uri.parse(url).path.orEmpty() }
        .getOrDefault("")
        .lowercase(Locale.US)
    return when {
        path.endsWith(".mp4") || path.endsWith(".m4v") -> "video/mp4"
        path.endsWith(".webm") -> "video/webm"
        path.endsWith(".mov") -> "video/quicktime"
        else -> null
    }
}
