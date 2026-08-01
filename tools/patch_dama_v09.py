from pathlib import Path

BROWSER = Path("dama/app/src/main/java/com/sajang/dama/BrowserCaptureActivity.kt")
GRADLE = Path("dama/app/build.gradle.kts")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing v0.9 patch target for {label}: {old[:160]!r}")
    return text.replace(old, new, 1)


def patch_browser() -> None:
    text = BROWSER.read_text()

    blocked_guard = '''        val host = runCatching { Uri.parse(url).host.orEmpty().lowercase() }.getOrDefault("")
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
'''
    isolated_open = '''        status(
            "격리 브라우저 연결 중",
            6,
            "ISOLATED_WEBVIEW\\n이 페이지는 담아 본체와 분리된 브라우저 프로세스에서 엽니다. 페이지가 열린 뒤 영상을 실제로 재생하세요.",
        )
'''
    text = replace_once(text, blocked_guard, isolated_open, "remove source-only domain block")

    text = replace_once(
        text,
        '            text = "담아 · 브라우저 감지"\n',
        '            text = "담아 · 격리 브라우저 감지"\n',
        "browser title",
    )

    text = replace_once(
        text,
        '            text = "브라우저 안에서 재생 버튼을 누르면 영상 요청을 찾습니다."\n',
        '            text = "페이지가 열린 뒤 재생 버튼을 누르면 실제 영상 요청을 찾습니다."\n',
        "browser guidance",
    )

    BROWSER.write_text(text)


def patch_version() -> None:
    text = GRADLE.read_text()
    text = text.replace('versionCode = 8', 'versionCode = 9')
    text = text.replace('versionName = "0.8.0"', 'versionName = "0.9.0"')
    if 'versionCode = 9' not in text or 'versionName = "0.9.0"' not in text:
        raise RuntimeError("v0.9 version patch failed")
    GRADLE.write_text(text)


def main() -> None:
    patch_browser()
    patch_version()


if __name__ == "__main__":
    main()
