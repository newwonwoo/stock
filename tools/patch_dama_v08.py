from pathlib import Path

MANIFEST = Path("dama/app/src/main/AndroidManifest.xml")
MAIN = Path("dama/app/src/main/java/com/sajang/dama/MainActivity.kt")
BROWSER = Path("dama/app/src/main/java/com/sajang/dama/BrowserCaptureActivity.kt")
GRADLE = Path("dama/app/build.gradle.kts")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing patch target for {label}: {old[:120]!r}")
    return text.replace(old, new, 1)


def patch_manifest() -> None:
    text = MANIFEST.read_text()
    old = '''        <activity
            android:name=".BrowserCaptureActivity"
            android:exported="true"
            android:launchMode="singleTop"
            android:label="담아">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
            <intent-filter>
                <action android:name="android.intent.action.SEND" />
                <category android:name="android.intent.category.DEFAULT" />
                <data android:mimeType="text/plain" />
            </intent-filter>
        </activity>
        <activity
            android:name=".MainActivity"
            android:exported="false"
            android:launchMode="singleTop" />
'''
    new = '''        <activity
            android:name=".BrowserCaptureActivity"
            android:exported="false"
            android:excludeFromRecents="true"
            android:launchMode="singleTop"
            android:process=":browser"
            android:label="담아 · 브라우저 감지" />
        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:launchMode="singleTop">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
            <intent-filter>
                <action android:name="android.intent.action.SEND" />
                <category android:name="android.intent.category.DEFAULT" />
                <data android:mimeType="text/plain" />
            </intent-filter>
        </activity>
'''
    text = replace_once(text, old, new, "manifest process split")
    MANIFEST.write_text(text)


def patch_main() -> None:
    text = MAIN.read_text()

    text = replace_once(
        text,
        '''        incoming = extractSharedText(intent)
        setContent {
''',
        '''        handleIntent(intent)
        setContent {
''',
        "main onCreate intent",
    )
    text = replace_once(
        text,
        '''        setIntent(intent)
        incoming = extractSharedText(intent)
    }

    private fun extractSharedText(intent: Intent?): String? =
''',
        '''        setIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(intent: Intent?) {
        if (intent?.action == ACTION_CAPTURED_DOWNLOAD) {
            controller.startCapturedDownload(
                context = this,
                url = intent.getStringExtra(EXTRA_CAPTURED_URL).orEmpty(),
                title = intent.getStringExtra(EXTRA_CAPTURED_TITLE).orEmpty(),
                type = intent.getStringExtra(EXTRA_CAPTURED_TYPE).orEmpty(),
                referer = intent.getStringExtra(EXTRA_CAPTURED_REFERER).orEmpty(),
                origin = intent.getStringExtra(EXTRA_CAPTURED_ORIGIN).orEmpty(),
                cookie = intent.getStringExtra(EXTRA_CAPTURED_COOKIE).orEmpty(),
                userAgent = intent.getStringExtra(EXTRA_CAPTURED_USER_AGENT).orEmpty(),
            )
            return
        }
        incoming = extractSharedText(intent)
    }

    companion object {
        const val ACTION_CAPTURED_DOWNLOAD = "com.sajang.dama.action.CAPTURED_DOWNLOAD"
        const val EXTRA_CAPTURED_URL = "captured_url"
        const val EXTRA_CAPTURED_TITLE = "captured_title"
        const val EXTRA_CAPTURED_TYPE = "captured_type"
        const val EXTRA_CAPTURED_REFERER = "captured_referer"
        const val EXTRA_CAPTURED_ORIGIN = "captured_origin"
        const val EXTRA_CAPTURED_COOKIE = "captured_cookie"
        const val EXTRA_CAPTURED_USER_AGENT = "captured_user_agent"
    }

    private fun extractSharedText(intent: Intent?): String? =
''',
        "main capture intent handler",
    )

    insert_before = '''    fun cancel(context: Context) {
'''
    method = '''    fun startCapturedDownload(
        context: Context,
        url: String,
        title: String,
        type: String,
        referer: String,
        origin: String,
        cookie: String,
        userAgent: String,
    ) {
        if (url.isBlank()) {
            val report = FailureAnalyzer.fromMessage("감지된 영상 주소가 비어 있습니다.")
            mutable.update {
                withLog(
                    it.copy(
                        phase = "브라우저 전달 실패",
                        phaseProgress = 100,
                        failure = report,
                    ),
                    report.title,
                )
            }
            return
        }

        val input = Data.Builder()
            .putString(BrowserDownloadWorker.KEY_URL, url)
            .putString(BrowserDownloadWorker.KEY_TITLE, title.ifBlank { "영상" })
            .putString(BrowserDownloadWorker.KEY_TYPE, type)
            .putString(BrowserDownloadWorker.KEY_REFERER, referer)
            .putString(BrowserDownloadWorker.KEY_ORIGIN, origin)
            .putString(BrowserDownloadWorker.KEY_COOKIE, cookie)
            .putString(BrowserDownloadWorker.KEY_USER_AGENT, userAgent)
            .build()
        val request = OneTimeWorkRequestBuilder<BrowserDownloadWorker>()
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build()
            )
            .setInputData(input)
            .build()
        val manager = WorkManager.getInstance(context)
        manager.enqueueUniqueWork(
            "dama_browser_${url.hashCode()}",
            ExistingWorkPolicy.REPLACE,
            request,
        )

        mutable.update {
            withLog(
                it.copy(
                    workId = request.id,
                    workTitle = title.ifBlank { "영상" },
                    workState = WorkInfo.State.ENQUEUED,
                    phase = "브라우저 영상 다운로드 대기 중",
                    phaseProgress = 0,
                    failure = null,
                ),
                "격리 브라우저가 감지한 영상 주소를 받았습니다.",
            )
        }

        AppScope.launch {
            manager.getWorkInfoByIdFlow(request.id).collect { infoOrNull ->
                val info = infoOrNull ?: return@collect
                when (info.state) {
                    WorkInfo.State.ENQUEUED -> updateWork("다운로드 대기 중", 0, info.state)
                    WorkInfo.State.BLOCKED -> updateWork("네트워크 연결 대기 중", 0, info.state)
                    WorkInfo.State.RUNNING -> {
                        val message = info.progress.getString(BrowserDownloadWorker.KEY_MESSAGE)
                            ?: "다운로드 중"
                        val progress = info.progress.getInt(BrowserDownloadWorker.KEY_PROGRESS, 0)
                        updateWork(message, progress, info.state)
                    }
                    WorkInfo.State.SUCCEEDED -> updateWork("저장 완료", 100, info.state)
                    WorkInfo.State.FAILED -> {
                        val report = FailureReport(
                            code = info.outputData.getString(BrowserDownloadWorker.KEY_FAILURE_CODE)
                                ?: "BROWSER_DOWNLOAD_FAILED",
                            title = info.outputData.getString(BrowserDownloadWorker.KEY_FAILURE_TITLE)
                                ?: "브라우저 영상 저장 실패",
                            detail = info.outputData.getString(BrowserDownloadWorker.KEY_FAILURE_DETAIL)
                                ?: "브라우저에서 전달된 영상 저장에 실패했습니다.",
                            action = info.outputData.getString(BrowserDownloadWorker.KEY_FAILURE_ACTION)
                                ?: "페이지를 다시 연 뒤 재생 직후 다운로드하세요.",
                            technical = info.outputData.getString(BrowserDownloadWorker.KEY_FAILURE_TECHNICAL)
                                ?: "기술 상세 없음",
                        )
                        mutable.update {
                            withLog(
                                it.copy(
                                    workState = info.state,
                                    phase = "저장 실패",
                                    phaseProgress = 100,
                                    failure = report,
                                ),
                                "실패 원인 분석 완료 · ${report.code}",
                            )
                        }
                    }
                    WorkInfo.State.CANCELLED -> {
                        val report = FailureAnalyzer.fromMessage("다운로드가 취소되었습니다.")
                        mutable.update {
                            withLog(
                                it.copy(
                                    workState = info.state,
                                    phase = "다운로드 취소됨",
                                    phaseProgress = 100,
                                    failure = report,
                                ),
                                "다운로드가 취소되었습니다.",
                            )
                        }
                    }
                }
            }
        }
    }

'''
    text = replace_once(text, insert_before, method + insert_before, "captured download method")

    browser_button_anchor = '''                    Button(
                        onClick = controller::analyze,
                        enabled = !state.analyzing && !workActive && state.url.isNotBlank(),
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(54.dp),
                        shape = RoundedCornerShape(15.dp),
                    ) {
                        Icon(Icons.Outlined.Search, null)
                        Spacer(Modifier.width(8.dp))
                        Text(
                            if (state.analyzing) "분석 중..." else "영상 찾기",
                            fontWeight = FontWeight.Bold,
                        )
                    }
'''
    browser_button = browser_button_anchor + '''                    Button(
                        onClick = {
                            val intent = Intent(context, BrowserCaptureActivity::class.java).apply {
                                action = Intent.ACTION_SEND
                                type = "text/plain"
                                putExtra(Intent.EXTRA_TEXT, state.url)
                            }
                            context.startActivity(intent)
                        },
                        enabled = !state.analyzing && !workActive && state.url.isNotBlank(),
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(50.dp),
                        shape = RoundedCornerShape(15.dp),
                    ) {
                        Icon(Icons.Outlined.Movie, null)
                        Spacer(Modifier.width(8.dp))
                        Text("격리 브라우저로 재생 감지", fontWeight = FontWeight.Bold)
                    }
'''
    text = replace_once(text, browser_button_anchor, browser_button, "browser launch button")
    MAIN.write_text(text)


def patch_browser() -> None:
    text = BROWSER.read_text()

    load_anchor = '''        detailView.text = "페이지를 여는 중입니다."
        if (webViewDestroyed) {
            status("안전 모드 소스 분석", 24, "WEBVIEW_SAFE_MODE\\n내장 브라우저가 종료되어 페이지 소스만 분석합니다.")
            runSourceProbe(true)
            return
        }
        webView.loadUrl(url)
'''
    load_new = '''        detailView.text = "페이지를 여는 중입니다."
        val host = runCatching { Uri.parse(url).host.orEmpty().lowercase() }.getOrDefault("")
        val sourceOnlyHosts = setOf(
            "njavtv.com",
            "www.njavtv.com",
            "pornhub.com",
            "www.pornhub.com",
            "mypikpak.com",
            "www.mypikpak.com",
        )
        if (host in sourceOnlyHosts) {
            status(
                "충돌 방지 안전 분석",
                24,
                "WEBVIEW_DOMAIN_BLOCKED\\n이 도메인은 WebView 충돌 이력이 있어 내장 브라우저를 열지 않고 HTML 소스만 분석합니다.",
            )
            runSourceProbe(true)
            return
        }
        if (webViewDestroyed) {
            status("안전 모드 소스 분석", 24, "WEBVIEW_SAFE_MODE\\n내장 브라우저가 종료되어 페이지 소스만 분석합니다.")
            runSourceProbe(true)
            return
        }
        webView.loadUrl(url)
'''
    text = replace_once(text, load_anchor, load_new, "source-only host guard")

    start_marker = '''    private fun startCapturedDownload() {
'''
    end_marker = '''    private fun observeWork(id: UUID) {
'''
    start = text.find(start_marker)
    end = text.find(end_marker)
    if start < 0 or end < 0 or end <= start:
        raise RuntimeError("browser download method boundaries not found")
    replacement = '''    private fun startCapturedDownload() {
        val media = candidates.getOrNull(spinner.selectedItemPosition) ?: return
        status("담아 본체로 전달 중", 50, "격리 브라우저를 닫고 본체에서 다운로드를 시작합니다.")
        val intent = Intent(this, MainActivity::class.java).apply {
            action = MainActivity.ACTION_CAPTURED_DOWNLOAD
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or
                Intent.FLAG_ACTIVITY_CLEAR_TOP or
                Intent.FLAG_ACTIVITY_SINGLE_TOP
            putExtra(MainActivity.EXTRA_CAPTURED_URL, media.url)
            putExtra(MainActivity.EXTRA_CAPTURED_TITLE, media.title)
            putExtra(MainActivity.EXTRA_CAPTURED_TYPE, media.type)
            putExtra(MainActivity.EXTRA_CAPTURED_REFERER, media.referer)
            putExtra(MainActivity.EXTRA_CAPTURED_ORIGIN, media.origin)
            putExtra(MainActivity.EXTRA_CAPTURED_COOKIE, media.cookie)
            putExtra(MainActivity.EXTRA_CAPTURED_USER_AGENT, media.userAgent)
        }
        startActivity(intent)
        finish()
    }

'''
    text = text[:start] + replacement + text[end:]
    BROWSER.write_text(text)


def patch_version() -> None:
    text = GRADLE.read_text()
    for old in ('versionCode = 5', 'versionCode = 6', 'versionCode = 7'):
        text = text.replace(old, 'versionCode = 8')
    for old in ('versionName = "0.5.0"', 'versionName = "0.6.0"', 'versionName = "0.7.0"'):
        text = text.replace(old, 'versionName = "0.8.0"')
    if 'versionCode = 8' not in text or 'versionName = "0.8.0"' not in text:
        raise RuntimeError("v0.8 version patch failed")
    GRADLE.write_text(text)


def main() -> None:
    patch_manifest()
    patch_main()
    patch_browser()
    patch_version()


if __name__ == "__main__":
    main()
