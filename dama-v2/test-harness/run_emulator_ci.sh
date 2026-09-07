#!/usr/bin/env bash
set -uo pipefail

AVD_NAME="dama-ci"
EMULATOR_LOG="/tmp/dama-emulator.log"
REPORT_DIR="dama-v2/app/build/reports/androidTests"
mkdir -p "$REPORT_DIR"

cleanup() {
  adb logcat -d > "$REPORT_DIR/final-logcat.txt" 2>/dev/null || true
  if [[ -f /tmp/dama-emulator.pid ]]; then
    adb emu kill >/dev/null 2>&1 || true
    kill "$(cat /tmp/dama-emulator.pid)" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

# The hosted Linux runner has no KVM. Launch manually so no third-party action
# sends an input keyevent before Android services have stabilized.
nohup emulator \
  -avd "$AVD_NAME" \
  -no-window \
  -gpu swiftshader_indirect \
  -noaudio \
  -no-boot-anim \
  -camera-back none \
  -no-metrics \
  -accel off \
  > "$EMULATOR_LOG" 2>&1 &
echo $! > /tmp/dama-emulator.pid

adb start-server

# Wait for the transport to become usable.
transport_ready=0
for _ in $(seq 1 180); do
  state=$(adb get-state 2>/dev/null || true)
  if [[ "$state" == "device" ]]; then
    transport_ready=1
    break
  fi
  sleep 2
done

if [[ "$transport_ready" -ne 1 ]]; then
  echo "ADB transport did not become ready"
  tail -n 200 "$EMULATOR_LOG" || true
  exit 1
fi

# Wait for Android framework boot completion.
boot_ready=0
for _ in $(seq 1 240); do
  completed=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)
  if [[ "$completed" == "1" ]]; then
    boot_ready=1
    break
  fi
  sleep 2
done

if [[ "$boot_ready" -ne 1 ]]; then
  echo "Android framework did not finish booting"
  adb shell getprop > "$REPORT_DIR/getprop-timeout.txt" 2>/dev/null || true
  tail -n 200 "$EMULATOR_LOG" || true
  exit 1
fi

# The framework reports boot complete before package/input/media services are
# always stable on software emulation. Verify them explicitly instead of
# sending a synthetic key event.
services_ready=0
for _ in $(seq 1 60); do
  package_ok=$(adb shell service check package 2>/dev/null | tr -d '\r' || true)
  activity_ok=$(adb shell service check activity 2>/dev/null | tr -d '\r' || true)
  media_ok=$(adb shell service check media.extractor 2>/dev/null | tr -d '\r' || true)
  if [[ "$package_ok" == *"found"* && "$activity_ok" == *"found"* && "$media_ok" == *"found"* ]]; then
    services_ready=1
    break
  fi
  sleep 2
done

if [[ "$services_ready" -ne 1 ]]; then
  echo "Required Android services did not stabilize"
  adb shell service list > "$REPORT_DIR/service-list-timeout.txt" 2>/dev/null || true
  tail -n 200 "$EMULATOR_LOG" || true
  exit 1
fi

adb shell settings put global window_animation_scale 0 || true
adb shell settings put global transition_animation_scale 0 || true
adb shell settings put global animator_duration_scale 0 || true
adb shell svc power stayon true || true

# Give WebView/MediaStore a final short settling window on the unaccelerated VM.
sleep 15

bash dama-v2/test-harness/run_android_emulator_tests.sh
