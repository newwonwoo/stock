from pathlib import Path

SETTINGS = Path("dama/settings.gradle.kts")
GRADLE = Path("dama/app/build.gradle.kts")
MANIFEST = Path("dama/app/src/main/AndroidManifest.xml")
MAIN = Path("dama/app/src/main/java/com/sajang/dama/MainActivity.kt")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing v1.2 patch target for {label}: {old[:180]!r}")
    return text.replace(old, new, 1)


def patch_settings() -> None:
    text = SETTINGS.read_text()
    text = replace_once(
        text,
        '    repositories { google(); mavenCentral() }\n}\nrootProject.name',
        '    repositories {\n        google()\n        mavenCentral()\n        maven { url = uri("https://maven.mozilla.org/maven2/") }\n    }\n}\nrootProject.name',
        "Mozilla Maven repository",
    )
    SETTINGS.write_text(text)


def patch_gradle() -> None:
    text = GRADLE.read_text()
    text = replace_once(
        text,
        '    implementation("org.jsoup:jsoup:1.18.3")\n',
        '    implementation("org.jsoup:jsoup:1.18.3")\n    implementation("org.mozilla.geckoview:geckoview:152.0.20260713164047")\n',
        "GeckoView dependency",
    )
    text = text.replace('versionCode = 11', 'versionCode = 12')
    text = text.replace('versionName = "1.1.0"', 'versionName = "1.2.0"')
    if 'versionCode = 12' not in text or 'versionName = "1.2.0"' not in text:
        raise RuntimeError("v1.2 version patch failed")
    GRADLE.write_text(text)


def patch_manifest() -> None:
    text = MANIFEST.read_text()
    anchor = '''        <activity
            android:name=".BrowserCaptureActivity"
            android:exported="false"
            android:excludeFromRecents="true"
            android:launchMode="singleTop"
            android:process=":browser"
            android:label="담아 · 브라우저 감지" />
'''
    replacement = '''        <activity
            android:name=".GeckoCaptureActivity"
            android:exported="false"
            android:excludeFromRecents="true"
            android:launchMode="singleTop"
            android:process=":browser"
            android:windowSoftInputMode="stateUnspecified|adjustResize"
            android:label="담아 · Gecko 안전 감지" />
        <activity
            android:name=".BrowserCaptureActivity"
            android:exported="false"
            android:excludeFromRecents="true"
            android:launchMode="singleTop"
            android:process=":legacy_webview"
            android:label="담아 · 기존 WebView 감지" />
'''
    text = replace_once(text, anchor, replacement, "Gecko activity manifest")
    MANIFEST.write_text(text)


def patch_main() -> None:
    text = MAIN.read_text()
    text = text.replace(
        'Intent(context, BrowserCaptureActivity::class.java)',
        'Intent(context, GeckoCaptureActivity::class.java)',
    )
    text = text.replace(
        'Text("격리 브라우저로 재생 감지", fontWeight = FontWeight.Bold)',
        'Text("Gecko 안전 브라우저로 재생 감지", fontWeight = FontWeight.Bold)',
    )
    if 'GeckoCaptureActivity::class.java' not in text:
        raise RuntimeError("MainActivity Gecko launch patch failed")
    MAIN.write_text(text)


def main() -> None:
    patch_settings()
    patch_gradle()
    patch_manifest()
    patch_main()


if __name__ == "__main__":
    main()
