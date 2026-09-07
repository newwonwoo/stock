from pathlib import Path

GRADLE = Path("dama/app/build.gradle.kts")
MANIFEST = Path("dama/app/src/main/assets/dama_capture/manifest.json")
BACKGROUND = Path("dama/app/src/main/assets/dama_capture/background.js")
ACTIVITY = Path("dama/app/src/main/java/com/sajang/dama/GeckoCaptureActivity.java")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing v1.3 patch target for {label}: {old[:160]!r}")
    return text.replace(old, new, 1)


def patch_gradle() -> None:
    text = GRADLE.read_text()
    text = text.replace('versionCode = 14', 'versionCode = 15')
    text = text.replace('versionName = "1.2.2"', 'versionName = "1.3.0"')
    if 'versionCode = 15' not in text or 'versionName = "1.3.0"' not in text:
        raise RuntimeError("v1.3 version patch failed")
    GRADLE.write_text(text)


def patch_manifest() -> None:
    text = MANIFEST.read_text()
    text = text.replace('"version": "1.0.0"', '"version": "1.1.0"')
    text = replace_once(
        text,
        '    "webRequest",\n    "geckoViewAddons"',
        '    "webRequest",\n    "nativeMessaging",\n    "geckoViewAddons"',
        "native messaging permission",
    )
    MANIFEST.write_text(text)


def patch_background() -> None:
    text = BACKGROUND.read_text()
    text = replace_once(
        text,
        'function publish(data) {\n  if (!data || !data.url || !/^https?:/i.test(data.url)) return;',
        '''function sendNative(data) {
  browser.runtime.sendNativeMessage("dama.capture", JSON.stringify(data)).catch(() => {});
}

function publish(data) {
  if (!data || !data.url || !/^https?:/i.test(data.url)) return;''',
        "native sender helper",
    )
    text = replace_once(
        text,
        '  browser.runtime.sendNativeMessage("dama.capture", JSON.stringify(data)).catch(() => {});\n}',
        '  sendNative(data);\n}',
        "publish native sender",
    )
    text += '''

sendNative({
  kind: "bridge-ready",
  extensionVersion: browser.runtime.getManifest().version,
  url: ""
});
'''
    BACKGROUND.write_text(text)


def patch_activity() -> None:
    text = ACTIVITY.read_text()
    old = '''            String url = json.optString("url", "").trim();
            if (!isSupportedMedia(url)) return;
            String pageUrl = json.optString("pageUrl", "").trim();'''
    new = '''            String kind = json.optString("kind", "").trim();
            if ("bridge-ready".equals(kind)) {
                String extensionVersion = json.optString("extensionVersion", "").trim();
                runOnUiThread(() -> status(
                        "감지 모듈 연결 완료",
                        12,
                        "네트워크 감지기가 연결됐습니다" +
                                (extensionVersion.isEmpty() ? "." : " · 확장 " + extensionVersion)
                ));
                return;
            }
            String url = json.optString("url", "").trim();
            if (!isSupportedMedia(url)) return;
            String pageUrl = json.optString("pageUrl", "").trim();'''
    text = replace_once(text, old, new, "bridge-ready handling")
    ACTIVITY.write_text(text)


def main() -> None:
    patch_gradle()
    patch_manifest()
    patch_background()
    patch_activity()


if __name__ == "__main__":
    main()
