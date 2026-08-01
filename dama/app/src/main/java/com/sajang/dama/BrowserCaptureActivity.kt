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
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
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
    private lateinit var status: TextView
    private lateinit var detail: TextView
    private lateinit var progress: ProgressBar
    private lateinit var spinner: Spinner
    private lateinit var downloadButton: Button
    private val candidates = mutableListOf<CapturedMedia>()
    private val candidateLabels = mutableListOf<String>()
    private lateinit var adapter: ArrayAdapter<String>
    private val handler = Handler(Looper.getMainLooper())
    private var pageTitle: String = "영상"

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
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            mediaPlaybackRequiresUserGesture = true
            mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
            allowFileAccess = false
            allowContentAccess = false
            builtInZoomControls = false
            displayZoomControls = false
        }
        webView.addJavascriptInterface(CaptureBridge(), "DamaCapture")
        webView.webChromeClient = WebChromeClient()
        webView.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView?, url: String?, favicon: android.graphics.Bitmap?) {
                status("페이지 연결 중", 8, "페이지를 불러오고 있습니다.")
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                pageTitle = view?.title?.takeIf { it.isNotBlank() } ?: "영상"
                status("재생 요청 대기", 20, "페이지에서 영상을 재생하세요. MP4·비암호화 HLS 요청을 감지합니다.")
                injectCaptureScript()
            }

            override fun shouldInterceptRequest(view: WebView?, request: WebResourceRequest?): android.webkit.WebResourceResponse? {
                request?.let {
                    captureIfMedia(
                        url = it.url.toString(),
                        headers = it.requestHeaders,
                        title = pageTitle,
                    )
                }
                return null
            }

            override fun onReceivedError(view: WebView?, request: WebResourceRequest?, error: WebResourceError?) {
                if (request?.isForMainFrame == true) {
                    status(
                        "페이지 연결 실패",
                        100,
                        "PAGE_LOAD_FAILED\n${error?.description ?: "페이지를 열 수 없습니다."}\n주소와 네트워크 상태를 확인하세요.",
                    )
                }
            }
        }

        val shared = if (intent?.action == Intent.ACTION_SEND) {
            intent.getStringExtra(Intent.EXTRA_TEXT)
        } else {
            intent?.dataString
        }
        shared?.let { extractUrl(it) }?.let {
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

        val title = TextView(this).apply {
            text = "담아 · 브라우저 감지"
            textSize = 22f
            setTextColor(Color.rgb(23, 32, 29))
            setTypeface(typeface, android.graphics.Typeface.BOLD)
            setPadding(0, 0, 0, dp(8))
        }
        root.addView(title)

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
        val analyzerButton = Button(this).apply {
            text = "일반 분석"
            setOnClickListener {
                val url = extractUrl(address.text.toString())
                startActivity(Intent(this@BrowserCaptureActivity, MainActivity::class.java).apply {
                    action = Intent.ACTION_SEND
                    type = "text/plain"
                    putExtra(Intent.EXTRA_TEXT, url ?: address.text.toString())
                })
            }
        }
        val diagnoseButton = Button(this).apply {
            text = "실패 분석"
            setOnClickListener { diagnoseNoCapture() }
        }
        modeRow.addView(analyzerButton, LinearLayout.LayoutParams(0, dp(46), 1f))
        modeRow.addView(diagnoseButton, LinearLayout.LayoutParams(0, dp(46), 1f))
        root.addView(modeRow)

        status = TextView(this).apply {
            text = "주소를 입력하고 페이지를 여세요."
            textSize = 16f
            setTextColor(Color.rgb(8, 76, 54))
            setTypeface(typeface, android.graphics.Typeface.BOLD)
            setPadding(0, dp(8), 0, dp(4))
        }
        root.addView(status)

        progress = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            max = 100
            this.progress = 0
        }
        root.addView(progress, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(8)))

        detail = TextView(this).apply {
            text = "브라우저 안에서 재생 버튼을 누르면 영상 요청을 찾습니다."
            textSize = 13f
            setTextColor(Color.rgb(93, 105, 100))
            setPadding(0, dp(5), 0, dp(6))
            maxLines = 5
        }
        root.addView(detail)

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
        candidates.clear()
        candidateLabels.clear()
        if (::adapter.isInitialized) adapter.notifyDataSetChanged()
        downloadButton.isEnabled = false
        detail.text = "페이지를 여는 중입니다."
        webView.loadUrl(url)
    }

    private fun captureIfMedia(url: String, headers: Map<String, String>, title: String) {
        if (!url.startsWith("http://") && !url.startsWith("https://")) return
        val lower = url.lowercase()
        val accept = headers.entries.firstOrNull { it.key.equals("Accept", true) }?.value.orEmpty().lowercase()
        val isHls = lower.contains(".m3u8") || lower.contains("format=m3u8") ||
            lower.contains("type=m3u8") || (lower.contains("manifest") && lower.contains("hls"))
        val isDirect = Regex("(?i)\\.(mp4|webm|mov|m4v)(?:$|[?#])").containsMatchIn(url) ||
            accept.startsWith("video/")
        if (!isHls && !isDirect) return
        if (candidates.any { it.url == url }) return

        val page = webView.url.orEmpty()
        val referer = headers.entries.firstOrNull { it.key.equals("Referer", true) }?.value
            ?.takeIf { it.isNotBlank() } ?: page
        val origin = runCatching {
            val uri = URI(page)
            "${uri.scheme}://${uri.authority}"
        }.getOrNull().orEmpty()
        val media = CapturedMedia(
            url = url,
            type = if (isHls) "HLS" else "DIRECT",
            title = title.ifBlank { "영상" },
            referer = referer,
            origin = origin,
            cookie = CookieManager.getInstance().getCookie(url).orEmpty(),
            userAgent = webView.settings.userAgentString.orEmpty(),
        )
        runOnUiThread {
            if (candidates.any { it.url == url }) return@runOnUiThread
            candidates += media
            val host = runCatching { Uri.parse(url).host }.getOrNull() ?: "영상 서버"
            candidateLabels += "${if (media.type == "HLS") "HLS" else "영상"} · $host"
            adapter.notifyDataSetChanged()
            spinner.setSelection(candidates.lastIndex)
            downloadButton.isEnabled = true
            status(
                "영상 요청 감지",
                45,
                "감지된 영상 ${candidates.size}개 · 재생이 시작되면 가장 적합한 항목을 선택하세요.",
            )
        }
    }

    private fun injectCaptureScript() {
        val script = """
            (function(){
              if(window.__damaCaptureInstalled){return;}
              window.__damaCaptureInstalled=true;
              function report(u){
                try{
                  if(typeof u==='string' && /^https?:/i.test(u)){
                    DamaCapture.found(u, document.title || '영상');
                  }
                }catch(e){}
              }
              function scan(){
                try{
                  document.querySelectorAll('video,source').forEach(function(v){
                    report(v.currentSrc); report(v.src);
                    if(v.getAttribute){report(v.getAttribute('src'));}
                  });
                  performance.getEntriesByType('resource').forEach(function(e){report(e.name);});
                }catch(e){}
              }
              new MutationObserver(scan).observe(document.documentElement || document,{subtree:true,childList:true,attributes:true});
              setInterval(scan,1200);
              scan();
            })();
        """.trimIndent()
        webView.evaluateJavascript(script, null)
    }

    private fun diagnoseNoCapture() {
        if (candidates.isNotEmpty()) {
            status("감지 정상", 45, "MEDIA_CAPTURED\n영상 요청 ${candidates.size}개를 찾았습니다. 목록에서 선택해 다운로드하세요.")
            return
        }
        val page = webView.url
        val message = if (page.isNullOrBlank()) {
            "PAGE_NOT_OPENED\n먼저 영상 페이지를 여세요."
        } else {
            "DYNAMIC_PLAYER_NOT_CAPTURED\n영상 요청이 아직 감지되지 않았습니다.\n재생 버튼을 누르고 광고 화면이 끝날 때까지 기다리세요. DRM·암호화 영상은 저장되지 않습니다."
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
        status("다운로드 준비 중", 1, "브라우저의 재생 정보로 영상 서버에 연결합니다.")
        observeWork(request.id)
    }

    private fun observeWork(id: UUID) {
        Thread {
            val info = runCatching { WorkManager.getInstance(this).getWorkInfoById(id).get() }.getOrNull()
            runOnUiThread {
                if (info != null) renderWork(info)
                if (info?.state?.isFinished != true) {
                    handler.postDelayed({ observeWork(id) }, 650)
                }
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
            status.text = title
            progress.progress = percent.coerceIn(0, 100)
            detail.text = description
        }
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
            webView.destroy()
        }
        super.onDestroy()
    }

    private inner class CaptureBridge {
        @JavascriptInterface
        fun found(url: String, title: String) {
            captureIfMedia(url, emptyMap(), title)
        }
    }

    private data class CapturedMedia(
        val url: String,
        val type: String,
        val title: String,
        val referer: String,
        val origin: String,
        val cookie: String,
        val userAgent: String,
    )
}
