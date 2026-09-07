from pathlib import Path


BROWSER_PATH = Path("dama/app/src/main/java/com/sajang/dama/BrowserCaptureActivity.kt")
GRADLE_PATH = Path("dama/app/build.gradle.kts")


def patch_v06_connection_handling(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    inside_open_page = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped == 'private var lastConsoleError = ""':
            out.append(line)
            out.append('    private var connectionRetryCount = 0')
            i += 1
            continue

        if stripped.startswith('private fun openPage()'):
            inside_open_page = True

        if inside_open_page and stripped == 'blobDetected = false':
            out.append(line)
            out.append('        connectionRetryCount = 0')
            i += 1
            continue

        if inside_open_page and stripped.startswith('private fun inspectRenderedPage()'):
            inside_open_page = False

        if 'var m=text.match(' in line:
            indent = line[: len(line) - len(line.lstrip())]
            out.append(indent + "var normalized=text.split('\\\\/').join('/');")
            out.append(indent + 'var urlPattern=new RegExp("https?://[^\\\\s\\\\x22\'<>]+","ig");')
            out.append(indent + 'var m=normalized.match(urlPattern)||[];')
            i += 1
            continue

        if 'm.slice(0,40).forEach(function(u){report(u.replace(' in line:
            indent = line[: len(line) - len(line.lstrip())]
            out.append(indent + 'm.slice(0,40).forEach(function(u){report(u);});')
            i += 1
            continue

        if 'override fun onReceivedError(' in line:
            indent = line[: len(line) - len(line.lstrip())]
            out.extend(
                [
                    indent + 'override fun onReceivedError(view: WebView?, request: WebResourceRequest?, error: WebResourceError?) {',
                    indent + '    if (request?.isForMainFrame == true) {',
                    indent + '        val description = error?.description?.toString().orEmpty()',
                    indent + '        val failedUrl = request.url.toString()',
                    indent + '        val isReset = description.contains("CONNECTION_RESET", true) ||',
                    indent + '            description.contains("connection reset", true)',
                    indent + '        if (isReset && connectionRetryCount < 2) {',
                    indent + '            connectionRetryCount += 1',
                    indent + '            val attempt = connectionRetryCount',
                    indent + '            status(',
                    indent + '                "연결 재시도",',
                    indent + '                10 + attempt * 4,',
                    indent + '                "CONNECTION_RESET_RETRY_$attempt\\n연결이 초기화되어 자동으로 다시 접속합니다. ($attempt/2)",',
                    indent + '            )',
                    indent + '            handler.postDelayed({',
                    indent + '                if (!webViewDestroyed) {',
                    indent + '                    webView.stopLoading()',
                    indent + '                    webView.clearCache(false)',
                    indent + '                    webView.settings.cacheMode = WebSettings.LOAD_NO_CACHE',
                    indent + '                    webView.loadUrl(failedUrl)',
                    indent + '                }',
                    indent + '            }, 900L * attempt)',
                    indent + '            return',
                    indent + '        }',
                    indent + '        val code = if (isReset) "CONNECTION_RESET" else "PAGE_LOAD_FAILED"',
                    indent + '        status(',
                    indent + '            "페이지 연결 실패",',
                    indent + '            100,',
                    indent + '            "$code\\n${description.ifBlank { "페이지를 열 수 없습니다." }}\\nHTML 직접 분석을 시도합니다.",',
                    indent + '        )',
                    indent + '        runSourceProbe(true)',
                    indent + '    }',
                    indent + '}',
                    '',
                ]
            )
            i += 1
            while i < len(lines) and 'override fun onRenderProcessGone(' not in lines[i]:
                i += 1
            continue

        out.append(line)
        i += 1

    patched = "\n".join(out) + "\n"
    if 'var urlPattern=new RegExp' not in patched:
        raise RuntimeError('safe URL pattern patch failed')
    if 'connectionRetryCount < 2' not in patched:
        raise RuntimeError('connection retry patch failed')
    return patched


def replace_once(text: str, old: str, new: str) -> str:
    if old not in text:
        raise RuntimeError(f"v0.7 patch target missing: {old[:100]!r}")
    return text.replace(old, new, 1)


def patch_v07_safe_mode(text: str) -> str:
    replacements = [
        (
            '    private var connectionRetryCount = 0\n',
            '    private var connectionRetryCount = 0\n    private var webViewDestroyed = false\n',
        ),
        (
            '        webView.setLayerType(View.LAYER_TYPE_HARDWARE, null)\n',
            '        webView.setLayerType(View.LAYER_TYPE_NONE, null)\n',
        ),
        (
            '        detailView.text = "페이지를 여는 중입니다."\n        webView.loadUrl(url)\n',
            '        detailView.text = "페이지를 여는 중입니다."\n        if (webViewDestroyed) {\n            status("안전 모드 소스 분석", 24, "WEBVIEW_SAFE_MODE\\n내장 브라우저가 종료되어 페이지 소스만 분석합니다.")\n            runSourceProbe(true)\n            return\n        }\n        webView.loadUrl(url)\n',
        ),
        (
            '        if (!::webView.isInitialized || webView.url.isNullOrBlank()) return\n',
            '        if (!::webView.isInitialized || webViewDestroyed || webView.url.isNullOrBlank()) return\n',
        ),
        (
            '        val page = extractUrl(address.text.toString()) ?: webView.url\n',
            '        val page = extractUrl(address.text.toString()) ?: if (!webViewDestroyed) webView.url else null\n',
        ),
        (
            '        val userAgent = webView.settings.userAgentString.orEmpty()\n',
            '        val userAgent = if (!webViewDestroyed) webView.settings.userAgentString.orEmpty() else DownloadWorker.USER_AGENT\n',
        ),
        (
            '        val page = webView.url.orEmpty().ifBlank { extractUrl(address.text.toString()).orEmpty() }\n',
            '        val page = (if (!webViewDestroyed) webView.url.orEmpty() else "").ifBlank { extractUrl(address.text.toString()).orEmpty() }\n',
        ),
        (
            '            userAgent = webView.settings.userAgentString.orEmpty(),\n',
            '            userAgent = if (!webViewDestroyed) webView.settings.userAgentString.orEmpty() else DownloadWorker.USER_AGENT,\n',
        ),
        (
            '    private fun injectCaptureScript() {\n        if (!::webView.isInitialized) return\n',
            '    private fun injectCaptureScript() {\n        if (!::webView.isInitialized || webViewDestroyed) return\n',
        ),
        (
            "                if(!window.__damaObserverInstalled){\n                  window.__damaObserverInstalled = true;\n                  new MutationObserver(scan).observe(document.documentElement || document,{subtree:true,childList:true,attributes:true});\n                  setInterval(scan,900);\n                }\n                scan();\n",
            "                if(!window.__damaEventHooksInstalled){\n                  window.__damaEventHooksInstalled = true;\n                  document.addEventListener('play', scan, true);\n                  document.addEventListener('loadedmetadata', scan, true);\n                  document.addEventListener('canplay', scan, true);\n                }\n                scan();\n                if(!window.__damaScanScheduled){\n                  window.__damaScanScheduled = true;\n                  setTimeout(scan,800);\n                  setTimeout(scan,2400);\n                }\n",
        ),
        (
            '''            override fun onRenderProcessGone(view: WebView?, detail: RenderProcessGoneDetail?): Boolean {
                status(
                    "브라우저 엔진 중단",
                    100,
                    "WEBVIEW_RENDERER_GONE\\nAndroid System WebView가 중단됐습니다. WebView와 Chrome을 업데이트한 뒤 다시 여세요.",
                )
                return true
            }
''',
            '''            override fun onRenderProcessGone(view: WebView?, detail: RenderProcessGoneDetail?): Boolean {
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
''',
        ),
        (
            '''        if (::webView.isInitialized) {
            webView.removeJavascriptInterface("DamaCapture")
            webView.stopLoading()
            webView.loadUrl("about:blank")
            webView.destroy()
        }
''',
            '''        if (::webView.isInitialized && !webViewDestroyed) {
            webView.removeJavascriptInterface("DamaCapture")
            webView.stopLoading()
            webView.loadUrl("about:blank")
            webView.destroy()
            webViewDestroyed = true
        }
''',
        ),
    ]

    for old, new in replacements:
        text = replace_once(text, old, new)
    return text


def main() -> None:
    source = BROWSER_PATH.read_text()
    source = patch_v06_connection_handling(source)
    source = patch_v07_safe_mode(source)
    BROWSER_PATH.write_text(source)

    gradle = GRADLE_PATH.read_text()
    gradle = gradle.replace('versionCode = 5', 'versionCode = 7')
    gradle = gradle.replace('versionCode = 6', 'versionCode = 7')
    gradle = gradle.replace('versionName = "0.5.0"', 'versionName = "0.7.0"')
    gradle = gradle.replace('versionName = "0.6.0"', 'versionName = "0.7.0"')
    if 'versionCode = 7' not in gradle or 'versionName = "0.7.0"' not in gradle:
        raise RuntimeError('version patch failed')
    GRADLE_PATH.write_text(gradle)


if __name__ == "__main__":
    main()
