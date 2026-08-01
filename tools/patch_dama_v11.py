from pathlib import Path

BROWSER = Path("dama/app/src/main/java/com/sajang/dama/BrowserCaptureActivity.kt")
GRADLE = Path("dama/app/build.gradle.kts")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing v1.1 patch target for {label}: {old[:180]!r}")
    return text.replace(old, new, 1)


def patch_browser() -> None:
    text = BROWSER.read_text()

    old_http = '''            override fun onReceivedHttpError(view: WebView?, request: WebResourceRequest?, errorResponse: WebResourceResponse?) {
                if (request?.isForMainFrame == true) {
                    val code = errorResponse?.statusCode ?: 0
                    status(
                        "페이지 응답 오류",
                        100,
                        "PAGE_HTTP_$code\\n사이트가 내장 브라우저 요청을 거부했을 수 있습니다. 소스 분석을 시도합니다.",
                    )
                    runSourceProbe(true)
                }
            }
'''
    new_http = '''            override fun onReceivedHttpError(view: WebView?, request: WebResourceRequest?, errorResponse: WebResourceResponse?) {
                if (request?.isForMainFrame != true) return
                val code = errorResponse?.statusCode ?: 0

                // Some Samsung/Chromium WebView builds emit status 0 immediately before
                // onReceivedError reports net::ERR_CONNECTION_RESET. Status 0 is not an
                // HTTP response and must not short-circuit the browser retry path.
                if (code <= 0) {
                    status(
                        "연결 상태 확인 중",
                        12,
                        "HTTP_STATUS_PENDING\\n유효한 HTTP 응답이 아직 없습니다. 실제 연결 오류를 확인한 뒤 자동 재접속합니다.",
                    )
                    return
                }

                status(
                    "페이지 응답 오류",
                    100,
                    "PAGE_HTTP_$code\\n서버가 HTTP $code 응답을 반환했습니다. 페이지 소스 분석을 시도합니다.",
                )
                runSourceProbe(true)
            }
'''
    text = replace_once(text, old_http, new_http, "ignore HTTP status zero")

    old_finished = '''            override fun onPageFinished(view: WebView?, url: String?) {
                pageTitle = view?.title?.takeIf { it.isNotBlank() } ?: "영상"
                status("재생 요청 대기", 20, "페이지에서 영상을 재생하세요. 빈 화면이면 자동으로 소스 분석을 시작합니다.")
                injectCaptureScript()
                handler.postDelayed({ inspectRenderedPage() }, 1800)
                handler.postDelayed({ injectCaptureScript() }, 3500)
            }
'''
    new_finished = '''            override fun onPageFinished(view: WebView?, url: String?) {
                val finalUrl = url.orEmpty()
                if (!finalUrl.startsWith("chrome-error://", true)) {
                    connectionRetryCount = 0
                    pageTitle = view?.title?.takeIf { it.isNotBlank() } ?: "영상"
                    status("재생 요청 대기", 20, "페이지에서 영상을 재생하세요. 빈 화면이면 자동으로 소스 분석을 시작합니다.")
                    injectCaptureScript()
                    handler.postDelayed({ inspectRenderedPage() }, 1800)
                    handler.postDelayed({ injectCaptureScript() }, 3500)
                }
            }
'''
    text = replace_once(text, old_finished, new_finished, "ignore WebView error page finish")

    text = text.replace('text = "담아 · 범용 격리 브라우저 감지"', 'text = "담아 · 범용 격리 브라우저 감지 v1.1"')
    BROWSER.write_text(text)


def patch_version() -> None:
    text = GRADLE.read_text()
    text = text.replace('versionCode = 10', 'versionCode = 11')
    text = text.replace('versionName = "1.0.0"', 'versionName = "1.1.0"')
    if 'versionCode = 11' not in text or 'versionName = "1.1.0"' not in text:
        raise RuntimeError("v1.1 version patch failed")
    GRADLE.write_text(text)


def main() -> None:
    patch_browser()
    patch_version()


if __name__ == "__main__":
    main()
