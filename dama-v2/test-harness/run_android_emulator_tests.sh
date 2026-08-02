#!/usr/bin/env bash
set -uo pipefail

REPORT_DIR="dama-v2/app/build/reports/androidTests/isolated"
APP_ID="com.sajang.dama"
TEST_RUNNER="com.sajang.dama.test/androidx.test.runner.AndroidJUnitRunner"
mkdir -p "$REPORT_DIR"

if ! gradle -p dama-v2 installDebug installDebugAndroidTest --stacktrace; then
  adb logcat -d > "dama-v2/app/build/reports/androidTests/logcat-install.txt" || true
  exit 1
fi

adb shell pm list instrumentation | tee "$REPORT_DIR/instrumentation.txt"
if ! grep -q "instrumentation:${TEST_RUNNER} (target=${APP_ID})" "$REPORT_DIR/instrumentation.txt"; then
  echo "Expected instrumentation runner was not installed: ${TEST_RUNNER} -> ${APP_ID}" >&2
  exit 1
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
  adb shell pm clear "$APP_ID" >/dev/null || true
  adb logcat -c || true

  test_name=$(printf '%s' "$test_selector" | tr '#.' '__')
  log_file="$REPORT_DIR/${test_name}.txt"
  logcat_file="$REPORT_DIR/${test_name}-logcat.txt"

  echo "=== RUN ${test_selector} ===" | tee "$log_file"
  timeout 300s adb shell am instrument -w -r \
    -e class "$test_selector" \
    "$TEST_RUNNER" \
    | tee -a "$log_file"
  command_status=${PIPESTATUS[0]}

  adb logcat -d > "$logcat_file" || true
  if [[ "$command_status" -ne 0 ]] || ! grep -q "OK (1 test)" "$log_file"; then
    echo "FAILED: ${test_selector} (status=${command_status})" | tee -a "$log_file"
    overall=1
  else
    echo "PASSED: ${test_selector}" | tee -a "$log_file"
  fi
done

exit "$overall"
