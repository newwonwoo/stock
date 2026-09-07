from pathlib import Path

BROWSER = Path("dama/app/src/main/java/com/sajang/dama/BrowserCaptureActivity.kt")
MAIN = Path("dama/app/src/main/java/com/sajang/dama/MainActivity.kt")
GRADLE = Path("dama/app/build.gradle.kts")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing v1.0 patch target for {label}: {old[:180]!r}")
    return text.replace(old, new, 1)


def patch_browser() -> None:
    text = BROWSER.read_text()

    text = replace_once(
        text,
        "    private var webViewDestroyed = false\n",
        "    private var webViewDestroyed = false\n    private var rendererRetryCount = 0\n",
        "browser retry field",
    )

    text = replace_once(
        text,
        "        setContentView(buildUi())\n\n        adapter = ArrayAdapter",
        "        setContentView(buildUi())\n        rendererRetryCount = intent.getIntExtra(MainActivity.EXTRA_BROWSER_RETRY_COUNT, 0)\n\n        adapter = ArrayAdapter",
        "browser retry extra",
    )

    old_renderer = '''            override fun onRenderProcessGone(view: WebView?, detail: RenderProcessGoneDetail?): Boolean {
                val crashed = view
                val didCrash = detail?.didCrash() == true
                webViewDestroyed = true
                handler.removeCallbacksAndMessages(null)
                runOnUiThread {
                    if (crashed != null) {
                        (crashed.parent as? ViewGroup)?.removeView(crashed)
                        runCatching { crashed.removeJavascriptInterface("DamaCapture") }
                        runCatching { crashed.stopLoading() }
                        runCatching { crashed.destroy() }
                    }
                    status(
                        "내장 브라우저 안전 종료",
                        55,
                        if (didCrash) {
                            "WEBVIEW_RENDERER_CRASHED\\n충돌한 WebView를 제거했습니다. 같은 페이지를 다시 로드하지 않고 HTML 소스 분석으로 전환합니다."
                        } else {
                            "WEBVIEW_RENDERER_KILLED\\n시스템이 WebView를 종료했습니다. HTML 소스 분석으로 전환합니다."
                        },
                    )
                    runSourceProbe(true)
                }
                return true
            }
'''
    new_renderer = '''            override fun onRenderProcessGone(view: WebView?, detail: RenderProcessGoneDetail?): Boolean {
                val crashedView = view
                val didCrash = detail?.didCrash() == true
                val priority = detail?.rendererPriorityAtExit() ?: -1
                val page = extractUrl(address.text.toString())
                    ?: runCatching { crashedView?.url }.getOrNull()
                    ?: ""
                val nextRetry = rendererRetryCount + 1

                webViewDestroyed = true
                handler.removeCallbacksAndMessages(null)
                if (crashedView != null) {
                    (crashedView.parent as? ViewGroup)?.removeView(crashedView)
                    runCatching { crashedView.removeJavascriptInterface("DamaCapture") }
                    runCatching { crashedView.stopLoading() }
                    runCatching { crashedView.destroy() }
                }

                val recovery = Intent(this@BrowserCaptureActivity, MainActivity::class.java).apply {
                    action = MainActivity.ACTION_BROWSER_RENDERER_GONE
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK or
                        Intent.FLAG_ACTIVITY_CLEAR_TOP or
                        Intent.FLAG_ACTIVITY_SINGLE_TOP
                    putExtra(MainActivity.EXTRA_BROWSER_URL, page)
                    putExtra(MainActivity.EXTRA_BROWSER_RETRY_COUNT, nextRetry)
                    putExtra(MainActivity.EXTRA_BROWSER_DID_CRASH, didCrash)
                    putExtra(MainActivity.EXTRA_BROWSER_PRIORITY, priority)
                }
                startActivity(recovery)
                finishAndRemoveTask()
                return true
            }
'''
    text = replace_once(text, old_renderer, new_renderer, "universal renderer recovery")
    BROWSER.write_text(text)


def patch_main() -> None:
    text = MAIN.read_text()

    text = replace_once(
        text,
        "import android.os.Build\nimport android.os.Bundle\n",
        "import android.os.Build\nimport android.os.Bundle\nimport android.os.Handler\nimport android.os.Looper\n",
        "main handler imports",
    )

    handle_anchor = '''    private fun handleIntent(intent: Intent?) {
        if (intent?.action == ACTION_CAPTURED_DOWNLOAD) {
'''
    handle_new = '''    private fun handleIntent(intent: Intent?) {
        if (intent?.action == ACTION_BROWSER_RENDERER_GONE) {
            val url = intent.getStringExtra(EXTRA_BROWSER_URL).orEmpty()
            val retryCount = intent.getIntExtra(EXTRA_BROWSER_RETRY_COUNT, 1)
            val didCrash = intent.getBooleanExtra(EXTRA_BROWSER_DID_CRASH, false)
            val priority = intent.getIntExtra(EXTRA_BROWSER_PRIORITY, -1)
            controller.reportBrowserRendererGone(retryCount, didCrash, priority)

            if (url.isNotBlank() && retryCount <= 1) {
                Handler(Looper.getMainLooper()).postDelayed({
                    val browserIntent = Intent(this, BrowserCaptureActivity::class.java).apply {
                        action = Intent.ACTION_SEND
                        type = "text/plain"
                        putExtra(Intent.EXTRA_TEXT, url)
                        putExtra(EXTRA_BROWSER_RETRY_COUNT, retryCount)
                    }
                    startActivity(browserIntent)
                }, 700L)
            } else if (url.isNotBlank()) {
                controller.acceptShared(url)
            }
            return
        }
        if (intent?.action == ACTION_CAPTURED_DOWNLOAD) {
'''
    text = replace_once(text, handle_anchor, handle_new, "main renderer intent")

    companion_anchor = '''        const val EXTRA_CAPTURED_USER_AGENT = "captured_user_agent"
'''
    companion_new = '''        const val EXTRA_CAPTURED_USER_AGENT = "captured_user_agent"
        const val ACTION_BROWSER_RENDERER_GONE = "com.sajang.dama.action.BROWSER_RENDERER_GONE"
        const val EXTRA_BROWSER_URL = "browser_url"
        const val EXTRA_BROWSER_RETRY_COUNT = "browser_retry_count"
        const val EXTRA_BROWSER_DID_CRASH = "browser_did_crash"
        const val EXTRA_BROWSER_PRIORITY = "browser_priority"
'''
    text = replace_once(text, companion_anchor, companion_new, "browser recovery constants")

    controller_anchor = '''    fun startCapturedDownload(
'''
    controller_method = '''    fun reportBrowserRendererGone(
        retryCount: Int,
        didCrash: Boolean,
        priority: Int,
    ) {
        val retrying = retryCount <= 1
        val code = if (didCrash) "WEBVIEW_RENDERER_CRASHED" else "WEBVIEW_RENDERER_KILLED"
        val report = FailureReport(
            code = code,
            title = if (retrying) "격리 브라우저 자동 복구" else "격리 브라우저 반복 종료",
            detail = if (didCrash) {
                "사이트 렌더링 중 별도 WebView 프로세스가 충돌했습니다. 담아 본체는 정상적으로 유지됩니다."
            } else {
                "메모리 또는 시스템 판단으로 별도 WebView 프로세스가 종료됐습니다. 담아 본체는 정상적으로 유지됩니다."
            },
            action = if (retrying) {
                "새 브라우저 프로세스로 한 번 자동 재시도합니다."
            } else {
                "동일 세션에서 두 번 종료되어 브라우저 재시도를 중단하고 안전 소스 분석으로 전환합니다."
            },
            technical = "retry=$retryCount, rendererPriorityAtExit=$priority",
        )
        mutable.update {
            withLog(
                it.copy(
                    phase = if (retrying) "브라우저 프로세스 재시작" else "안전 분석 전환",
                    phaseProgress = if (retrying) 35 else 100,
                    failure = report,
                ),
                "${report.title} · $code",
            )
        }
    }

'''
    text = replace_once(text, controller_anchor, controller_method + controller_anchor, "renderer status method")
    MAIN.write_text(text)


def patch_version() -> None:
    text = GRADLE.read_text()
    text = text.replace('versionCode = 9', 'versionCode = 10')
    text = text.replace('versionName = "0.9.0"', 'versionName = "1.0.0"')
    if 'versionCode = 10' not in text or 'versionName = "1.0.0"' not in text:
        raise RuntimeError("v1.0 version patch failed")
    GRADLE.write_text(text)


def main() -> None:
    patch_browser()
    patch_main()
    patch_version()


if __name__ == "__main__":
    main()
