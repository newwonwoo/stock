package com.sajang.dama

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.webkit.ConsoleMessage
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.Spinner
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import java.net.URI
import java.util.UUID

class BrowserCaptureActivity : ComponentActivity() {
    private lateinit var address: EditText
    private lateinit var webView: WebView
    private lateinit var statusView: TextView
    private lateinit var detailView: TextView
    private lateinit var progressView: ProgressBar
    private lateinit var spinner: Spinner
    private lateinit var downloadButton: Button
    private val candidates = mutableListOf<CapturedMedia>()
    private val candidateLabels = mutableListOf<String>()
    private lateinit var adapter: ArrayAdapter<String>
    private val handler = Handler(Looper.getMainLooper())
    private var pageTitle: String = "영상"
    private var sourceProbeRunning = false
    private var blobDetected = false
    private var lastConsoleError = ""

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestNotificationPermission()
        setContentView(buildUi())

        adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, candidateLabels)
        spinner.adapter = adapter

        WebView.setWebContentsDebuggingEnabled(false)
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true)
        webView.setBackgroundColor(Color.WHITE)
        webView.setLayerType(View.LAYER_TYPE_HARDWARE, null)
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            mediaPlaybackRequiresUserGesture = true
            mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
            allowFileAccess = false
            allowContentAccess = false
            builtInZoomControls = false
            displayZoomControls = false
            loadsImagesAutomatically = true
            useWideViewPort = true
            loadWithOverviewMode = true
            cacheMode = WebSettings.LOAD_DEFAULT
            javaScriptCanOpenWindowsAutomatically = true
            setSupportMultipleWindows(false)
            userAgentString = browserLikeUserAgent(userAgentString)
        }

        webView.addJavascriptInterface(CaptureBridge(), "DamaCapture")
        webView.webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(consoleMessage: ConsoleMessage?): Boolean {
                val message = consoleMessage?.message().orEmpty()
                if (message.contains("error", true) || message.contains("blocked", true) || message.contains("denied", true)) {
                    lastConsoleError = message.take(220)
                }
                return super.onConsoleMessage(consoleMessage)
            }

            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                if (newProgress in 1..99 && candidates.isEmpty()) {
                    status("페이지 로딩 중", (newProgress * 0.18).toInt().coerceAtLeast(2), "브라우저 콘텐츠를 불러오고 있습니다. $newProgress%")
                }
            }
        }

        webView.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView?, url: String?, favicon: android.graphics.Bitmap?) {
                blobDetected = false
                lastConsoleError = ""
                status("페이지 연결 중", 8, "페이지를 불러오고 있습니다.")
                handler.postDelayed({ injectCaptureScript() }, 250)
            }

            override fun onPageCommitVisible(view: WebView?, url: String?) {
                status("페이지 표시 중", 16, "페이지가 표시됐습니다. 영상 재생 버튼을 누르세요.")
                injectCaptureScript()
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                pageTitle = view?.title?.takeIf { it.isNotBlank() } ?: "영상"
                status("재생 요청 대기", 20, "페이지에서 영상을 재생하세요. 빈 화면이면 자동으로 소스 분석을 시작합니다.")
                injectCaptureScript()
                handler.postDelayed({ inspectRenderedPage() }, 1800)
                handler.postDelayed({ injectCaptureScript() }, 3500)
            }

            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                val target = request?.url?.toString().orEmpty()
                return if (target.startsWith("http://") || target.startsWith("https://")) {
                    false
                } else {
                    true
                }
            }

            override fun shouldInterceptRequest(view: WebView?, request: WebResourceRequest?): WebResourceResponse? {
                request?.let {
                    captureIfMedia(
                        url = it.url.toString(),
                        headers = it.requestHeaders,
                        title = pageTitle,
                    )
                }
                return null
            }

            override fun onReceivedHttpError(view: WebView?, request: WebResourceRequest?, errorResponse: WebResourceResponse?) {
                if (request?.isForMainFrame == true) {
                    val code = errorResponse?.statusCode ?: 0
                    status(
                        "페이지 응답 오류",
                        100,
                        "PAGE_HTTP_$code\n사이트가 내장 브라우저 요청을 거부했을 수 있습니다. 소스 분석을 시도합니다.",
                    )
                    runSourceProbe(true)
                }
            }

            override fun onReceivedError(view: WebView?, request: WebResourceRequest?, error: WebResourceError?) {
                if (request?.isForMainFrame == true) {
                    status(
                        "페이지 연결 실패",
                        100,
                        "PAGE_LOAD_FAILED\n${error?.description ?: "페이지를 열 수 없습니다."}\n소스 분석을 시도합니다.",
                    )
                    runSourceProbe(true)
                }
            }

            override fun onRenderProcessGone(view: WebView?, detail: RenderProcessGoneDetail?): Boolean {
                status(
                    "브라우저 엔진 중단",
                    100,
                    "WEBVIEW_RENDERER_GONE\nAndroid System WebView가 중단됐습니다. WebView와 Chrome을 업데이트한 뒤 다시 여세요.",
                )
                return true
            }
        }

        val shared = if (intent?.action == Intent.ACTION_SEND) {
            intent.getStringExtra(Intent.EXTRA_TEXT)
        } else {
            intent?.dataString
        }
        shared?.let(::extractUrl)?.let {
            address.setText(it)
            openPage()
        }
    }

    private fun buildUi(): View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.WHITE)
            setPadding(dp(14), dp(10), dp(14), dp(10))
        }

        root.addView(TextView(this).apply {
            text = "담아 · 브라우저 감지"
            textSize = 22f
            setTextColor(Color.rgb(23, 32, 29))
            setTypeface(typeface, android.graphics.Typeface.BOLD)
            setPadding(0, 0, 0, dp(8))
        })

        val addressRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        address = EditText(this).apply {
            hint = "영상 페이지 주소"
            isSingleLine = true
            textSize = 14f
            layoutParams = LinearLayout.LayoutParams(0, dp(50), 1f)
        }
        val openButton = Button(this).apply {
            text = "열기"
            setOnClickListener { openPage() }
        }
        addressRow.addView(address)
        addressRow.addView(openButton, LinearLayout.LayoutParams(dp(82), dp(50)))
        root.addView(addressRow)

        val modeRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        val sourceButton = Button(this).apply {
            text = "소스 분석"
            setOnClickListener { runSourceProbe(false) }
        }
        val diagnoseButton = Button(this).apply {
            text = "실패 분석"
            setOnClickListener { diagnoseNoCapture() }
        }
        modeRow.addView(sourceButton, LinearLayout.LayoutParams(0, dp(46), 1f))
        modeRow.addView(diagnoseButton, LinearLayout.LayoutParams(0, dp(46), 1f))
        root.addView(modeRow)

        statusView = TextView(this).apply {
            text = "주소를 입력하고 페이지를 여세요."
            textSize = 16f
            setTextColor(Color.rgb(8, 76, 54))
            setTypeface(typeface, android.graphics.Typeface.BOLD)
            setPadding(0, dp(8), 0, dp(4))
        }
        root.addView(statusView)

        progressView = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            max = 100
            progress = 0
        }
        root.addView(progressView, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(8)))

        detailView = TextView(this).apply {
            text = "브라우저 안에서 재생 버튼을 누르면 영상 요청을 찾습니다."
            textSize = 13f
            setTextColor(Color.rgb(93, 105, 100))
            setPadding(0, dp(5), 0, dp(6))
            maxLines = 7
        }
        root.addView(detailView)

        val captureRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        spinner = Spinner(this)
        downloadButton = Button(this).apply {
            text = "다운로드"
            isEnabled = false
            setOnClickListener { startCapturedDownload() }
        }
        captureRow.addView(spinner, LinearLayout.LayoutParams(0, dp(48), 1f))
        captureRow.addView(downloadButton, LinearLayout.LayoutParams(dp(118), dp(48)))
        root.addView(captureRow)

        webView = WebView(this)
        root.addView(webView, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        return root
    }

    private fun openPage() {
        val url = extractUrl(address.text.toString())
        if (url == null) {
            status("주소 오류", 100, "INVALID_URL\nhttp 또는 https 주소를 입력하세요.")
            return
        }
        sourceProbeRunning = false
        blobDetected = false
        candidates.clear()
        candidateLabels.clear()
        if (::adapter.isInitialized) adapter.notifyDataSetChanged()
        downloadButton.isEnabled = false
        detailView.text = "페이지를 여는 중입니다."
        webView.loadUrl(url)
    }

    private fun inspectRenderedPage() {
        if (!::webView.isInitialized || webView.url.isNullOrBlank()) return
        webView.evaluateJavascript(
            "(function(){try{return String((document.body&&document.body.innerHTML||'').length)}catch(e){return '0'}})()"
        ) { raw ->
            val length = raw.filter(Char::isDigit).toIntOrNull() ?: 0
            if (length < 120) {
                val extra = lastConsoleError.takeIf { it.isNotBlank() }?.let { "\nJS: $it" }.orEmpty()
                status(
                    "내장 브라우저 차단 감지",
                    25,
                    "WEBVIEW_BLANK_PAGE\n페이지 본문이 비어 있습니다.$extra\n페이지 소스를 직접 분석합니다.",
                )
                runSourceProbe(true)
            } else if (candidates.isEmpty()) {
                status(
                    "재생 요청 대기",
                    22,
                    "페이지는 열렸습니다. 영상을 실제로 재생하세요. 감지되지 않으면 소스 분석을 누르세요.",
                )
            }
        }
    }

    private fun runSourceProbe(auto: Boolean) {
        if (sourceProbeRunning) return
        val page = extractUrl(address.text.toString()) ?: webView.url
        if (page.isNullOrBlank()) {
            status("소스 분석 불가", 100, "PAGE_NOT_OPENED\n먼저 주소를 입력하세요.")
            return
        }
        sourceProbeRunning = true
        status(
            "페이지 소스 분석 중",
            30,
            if (auto) "내장 브라우저가 비어 있어 HTML과 영상 메타데이터를 직접 확인합니다." else "HTML과 연결된 미디어 정의를 확인합니다.",
        )
        val userAgent = webView.settings.userAgentString.orEmpty()
        val cookie = CookieManager.getInstance().getCookie(page).orEmpty()
        Thread {
            val result = SourceProbe.probe(page, userAgent, cookie)
            runOnUiThread {
                sourceProbeRunning = false
                result.media.forEach { media ->
                    addCandidate(
                        url = media.url,
                        type = media.type,
                        title = pageTitle,
                        quality = media.quality,
                        headers = emptyMap(),
                    )
                }
                if (result.media.isNotEmpty()) {
                    status(
                        "소스 분석 완료",
                        48,
                        "${result.code}\n${result.detail}\n목록에서 화질을 선택해 다운로드하세요.",
                    )
                } else {
                    status(
                        "소스 분석 실패",
                        100,
                        "${result.code}\n${result.detail}\n사이트가 세션·서명·DRM으로 주소를 보호하면 저장할 수 없습니다.",
                    )
                }
            }
        }.start()
    }

    private fun captureIfMedia(url: String, headers: Map<String, String>, title: String) {
        if (!url.startsWith("http://") && !url.startsWith("https://")) return
        val lower = url.lowercase()
        if (Regex("(?i)\\.(m4s|ts|aac|jpg|jpeg|png|gif|webp)(?:$|[?#])").containsMatchIn(url)) return
        val accept = headers.entries.firstOrNull { it.key.equals("Accept", true) }?.value.orEmpty().lowercase()
        val isHls = lower.contains(".m3u8") || lower.contains("format=m3u8") ||
            lower.contains("type=m3u8") || (lower.contains("manifest") && lower.contains("hls")) ||
            lower.contains("master.m3u")
        val isDirect = Regex("(?i)\\.(mp4|webm|mov|m4v)(?:$|[?#])").containsMatchIn(url) ||
            accept.startsWith("video/")
        if (!isHls && !isDirect) return
        val quality = Regex("(?i)(2160|1440|1080|720|480|360|240)p").find(url)
            ?.groupValues?.getOrNull(1)?.plus("p") ?: if (isHls) "자동" else "원본"
        addCandidate(url, if (isHls) "HLS" else "DIRECT", title, quality, headers)
    }

    private fun addCandidate(
        url: String,
        type: String,
        title: String,
        quality: String,
        headers: Map<String, String>,
    ) {
        if (candidates.any { it.url == url }) return
        val page = webView.url.orEmpty().ifBlank { extractUrl(address.text.toString()).orEmpty() }
        val referer = headers.entries.firstOrNull { it.key.equals("Referer", true) }?.value
            ?.takeIf { it.isNotBlank() } ?: page
        val origin = runCatching {
            val uri = URI(page)
            "${uri.scheme}://${uri.authority}"
        }.getOrNull().orEmpty()
        val mediaCookie = CookieManager.getInstance().getCookie(url).orEmpty()
        val pageCookie = CookieManager.getInstance().getCookie(page).orEmpty()
        val media = CapturedMedia(
            url = url,
            type = type,
            title = title.ifBlank { "영상" },
            quality = quality,
            referer = referer,
            origin = origin,
            cookie = mediaCookie.ifBlank { pageCookie },
            userAgent = webView.settings.userAgentString.orEmpty(),
        )
        runOnUiThread {
            if (candidates.any { it.url == url }) return@runOnUiThread
            candidates += media
            val host = runCatching { Uri.parse(url).host }.getOrNull() ?: "영상 서버"
            candidateLabels += "${media.quality} · ${if (media.type == "HLS") "HLS" else "영상"} · $host"
            adapter.notifyDataSetChanged()
            spinner.setSelection(candidates.lastIndex)
            downloadButton.isEnabled = true
            status(
                "영상 요청 감지",
                45,
                "감지된 영상 ${candidates.size}개 · 화질과 서버를 확인해 선택하세요.",
            )
        }
    }

    private fun injectCaptureScript() {
        if (!::webView.isInitialized) return
        val script = """
            (function(){
              try {
                function report(u){
                  try {
                    if(typeof u !== 'string') return;
                    if(/^blob:/i.test(u)){ DamaCapture.blobFound(document.title || '영상'); return; }
                    if(/^https?:/i.test(u)){ DamaCapture.found(u, document.title || '영상'); }
                  } catch(e) {}
                }
                if(!window.__damaHooksInstalled){
                  window.__damaHooksInstalled = true;
                  var oldFetch = window.fetch;
                  if(oldFetch){
                    window.fetch = function(input, init){
                      try { report(typeof input === 'string' ? input : input && input.url); } catch(e) {}
                      return oldFetch.apply(this, arguments).then(function(r){ try{report(r.url);}catch(e){} return r; });
                    };
                  }
                  var oldOpen = XMLHttpRequest.prototype.open;
                  XMLHttpRequest.prototype.open = function(method, url){ try{report(String(url));}catch(e){} return oldOpen.apply(this, arguments); };
                  var oldCreate = URL.createObjectURL;
                  if(oldCreate){ URL.createObjectURL = function(o){ var u=oldCreate.apply(this,arguments); try{DamaCapture.blobFound(document.title||'영상');}catch(e){} return u; }; }
                }
                function scan(){
                  try {
                    document.querySelectorAll('video,source').forEach(function(v){
                      report(v.currentSrc); report(v.src);
                      if(v.getAttribute) report(v.getAttribute('src'));
                    });
                    performance.getEntriesByType('resource').forEach(function(e){report(e.name);});
                    document.querySelectorAll('script').forEach(function(s){
                      var text=s.textContent||'';
                      var m=text.match(/https?:\\?\\?\\/\\?\\/[^\\s\"'<>]+/ig)||[];
                      m.slice(0,40).forEach(function(u){report(u.replace(/\\\\\//g,'/'));});
                    });
                  } catch(e) {}
                }
                if(!window.__damaObserverInstalled){
                  window.__damaObserverInstalled = true;
                  new MutationObserver(scan).observe(document.documentElement || document,{subtree:true,childList:true,attributes:true});
                  setInterval(scan,900);
                }
                scan();
              } catch(e) {}
            })();
        """.trimIndent()
        webView.evaluateJavascript(script, null)
    }

    private fun diagnoseNoCapture() {
        if (candidates.isNotEmpty()) {
            status("감지 정상", 45, "MEDIA_CAPTURED\n영상 요청 ${candidates.size}개를 찾았습니다. 목록에서 선택하세요.")
            return
        }
        val page = webView.url
        val message = when {
            page.isNullOrBlank() -> "PAGE_NOT_OPENED\n먼저 영상 페이지를 여세요."
            sourceProbeRunning -> "SOURCE_PROBE_RUNNING\n페이지 소스를 분석하고 있습니다."
            blobDetected -> "BLOB_PLAYER_DETECTED\n브라우저의 blob 재생은 직접 저장할 수 없습니다. 원본 스트림 주소를 소스에서 찾지 못했습니다."
            lastConsoleError.isNotBlank() -> "WEBVIEW_SCRIPT_ERROR\n$lastConsoleError\n사이트 스크립트가 WebView에서 실행되지 않았습니다."
            else -> "DYNAMIC_PLAYER_NOT_CAPTURED\n영상 요청이 감지되지 않았습니다. 재생 후 소스 분석을 실행하세요."
        }
        status("실패 원인 분석", 100, message)
    }

    private fun startCapturedDownload() {
        val media = candidates.getOrNull(spinner.selectedItemPosition) ?: return
        val data = Data.Builder()
            .putString(BrowserDownloadWorker.KEY_URL, media.url)
            .putString(BrowserDownloadWorker.KEY_TITLE, media.title)
            .putString(BrowserDownloadWorker.KEY_TYPE, media.type)
            .putString(BrowserDownloadWorker.KEY_REFERER, media.referer)
            .putString(BrowserDownloadWorker.KEY_ORIGIN, media.origin)
            .putString(BrowserDownloadWorker.KEY_COOKIE, media.cookie)
            .putString(BrowserDownloadWorker.KEY_USER_AGENT, media.userAgent)
            .build()
        val request = OneTimeWorkRequestBuilder<BrowserDownloadWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setInputData(data)
            .build()
        WorkManager.getInstance(this).enqueueUniqueWork(
            "dama_browser_${media.url.hashCode()}",
            ExistingWorkPolicy.REPLACE,
            request,
        )
        downloadButton.isEnabled = false
        status("다운로드 준비 중", 1, "브라우저 세션 정보로 영상 서버에 연결합니다.")
        observeWork(request.id)
    }

    private fun observeWork(id: UUID) {
        Thread {
            val info = runCatching { WorkManager.getInstance(this).getWorkInfoById(id).get() }.getOrNull()
            runOnUiThread {
                if (info != null) renderWork(info)
                if (info?.state?.isFinished != true) handler.postDelayed({ observeWork(id) }, 650)
            }
        }.start()
    }

    private fun renderWork(info: WorkInfo) {
        val percent = info.progress.getInt(BrowserDownloadWorker.KEY_PROGRESS, 0)
        val message = info.progress.getString(BrowserDownloadWorker.KEY_MESSAGE)
        when (info.state) {
            WorkInfo.State.ENQUEUED -> status("다운로드 대기 중", 0, "작업을 준비하고 있습니다.")
            WorkInfo.State.BLOCKED -> status("네트워크 대기 중", 0, "인터넷 연결을 확인하세요.")
            WorkInfo.State.RUNNING -> status(message ?: "다운로드 중", percent, "진행률 $percent%")
            WorkInfo.State.SUCCEEDED -> {
                status("저장 완료", 100, "내 파일 > 동영상 > 담아에 저장했습니다.")
                downloadButton.isEnabled = true
            }
            WorkInfo.State.FAILED -> {
                val code = info.outputData.getString(BrowserDownloadWorker.KEY_FAILURE_CODE) ?: "DOWNLOAD_FAILED"
                val title = info.outputData.getString(BrowserDownloadWorker.KEY_FAILURE_TITLE) ?: "저장 실패"
                val reason = info.outputData.getString(BrowserDownloadWorker.KEY_FAILURE_DETAIL).orEmpty()
                val action = info.outputData.getString(BrowserDownloadWorker.KEY_FAILURE_ACTION).orEmpty()
                status(title, 100, "$code\n$reason\n$action")
                downloadButton.isEnabled = true
            }
            WorkInfo.State.CANCELLED -> {
                status("다운로드 취소", 100, "CANCELLED\n작업이 취소되었습니다.")
                downloadButton.isEnabled = true
            }
        }
    }

    private fun status(title: String, percent: Int, description: String) {
        runOnUiThread {
            statusView.text = title
            progressView.progress = percent.coerceIn(0, 100)
            detailView.text = description
        }
    }

    private fun browserLikeUserAgent(default: String): String {
        val cleaned = default
            .replace("; wv", "")
            .replace("Version/4.0 ", "")
        return if (cleaned.contains("Chrome/")) cleaned else DownloadWorker.USER_AGENT
    }

    private fun extractUrl(value: String): String? =
        Regex("https?://\\S+", RegexOption.IGNORE_CASE).find(value.trim())?.value
            ?.trimEnd('.', ',', ')', ']', '}', '>', '"', '\'')

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 40)
        }
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    override fun onBackPressed() {
        if (::webView.isInitialized && webView.canGoBack()) webView.goBack() else super.onBackPressed()
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        if (::webView.isInitialized) {
            webView.removeJavascriptInterface("DamaCapture")
            webView.stopLoading()
            webView.loadUrl("about:blank")
            webView.destroy()
        }
        super.onDestroy()
    }

    private inner class CaptureBridge {
        @JavascriptInterface
        fun found(url: String, title: String) {
            captureIfMedia(url.replace("\\/", "/"), emptyMap(), title)
        }

        @JavascriptInterface
        fun blobFound(title: String) {
            blobDetected = true
            if (candidates.isEmpty()) {
                runOnUiThread {
                    status("blob 재생 감지", 26, "BLOB_PLAYER_DETECTED\n원본 스트림 주소를 찾기 위해 페이지 소스를 분석합니다.")
                    runSourceProbe(true)
                }
            }
        }
    }

    private data class CapturedMedia(
        val url: String,
        val type: String,
        val title: String,
        val quality: String,
        val referer: String,
        val origin: String,
        val cookie: String,
        val userAgent: String,
    )
}
