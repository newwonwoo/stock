#!/usr/bin/env bash
set -uo pipefail

REPORT_DIR="dama-v2/app/build/reports/androidTests/isolated"
mkdir -p "$REPORT_DIR"

gradle -p dama-v2 installDebug installDebugAndroidTest --stacktrace
install_status=$?
if [[ "$install_status" -ne 0 ]]; then
  adb logcat -d > dama-v2/app/build/reports/androidTests/logcat-install.txt || true
  exit "$install_status"
fi

tests=(
  "com.sajang.dama.next.MainActivityTest#invalidInputProducesFailureAndDiagnosticFile"
  "com.sajang.dama.next.MainActivityTest#directMp4IsDownloadedAndSavedToMediaStore"
  "com.sajang.dama.next.MainActivityTest#controlledFixturePageIsExtractedByAndroidYtDlp"
  "com.sajang.dama.next.BrowserCaptureActivityTest#pikpakPublicJsonExtractsDownloadAndMediaLinksOnAndroid"
  "com.sajang.dama.next.BrowserCaptureActivityTest#capturesDirectLinkFromLocalJsonFixture"
  "com.sajang.dama.next.BrowserCaptureActivityTest#capturesHlsLinkFromLocalWindowFixture"
)

overall=0
for test_selector in "${tests[@]}"; do
  adb shell pm clear com.sajang.dama >/dev/null || true
  adb logcat -c || true

  test_name=$(printf '%s' "$test_selector" | tr '#.' '__')
  log_file="$REPORT_DIR/${test_name}.txt"

  timeout 180s adb shell am instrument -w -r \
    -e class "$test_selector" \
    com.sajang.dama.test/androidx.test.runner.AndroidJUnitRunner \
    | tee "$log_file"
  command_status=${PIPESTATUS[0]}

  adb logcat -d > "$REPORT_DIR/${test_name}-logcat.txt" || true

  if [[ "$command_status" -ne 0 ]] || ! grep -q "OK (1 test)" "$log_file"; then
    overall=1
  fi
done

exit "$overall"
