#!/usr/bin/env bash
set -euo pipefail

ESP_IP="${ESP_IP:-192.168.8.235}"
PORT="${PORT:-80}"
BASE_URL="http://${ESP_IP}:${PORT}"

buttons=(
  Y X B A L R ZL ZR
  MINUS PLUS L_STICK R_STICK
  HOME CAPTURE UP DOWN LEFT RIGHT
)

call() {
  local path="$1"
  echo "-> ${BASE_URL}${path}"
  curl -fsS "${BASE_URL}${path}"
  echo
}

echo "=== OpenSwitchBridge HTTP API Batch Test ==="
echo "Target: ${BASE_URL}"
echo

echo "[1/5] health"
call "/health"

echo "[2/5] single buttons"
for button in "${buttons[@]}"; do
  call "/input?buttons=${button}&ms=120"
  sleep 0.15
done

echo "[3/5] combo chords"
call "/input?buttons=A+B&ms=300"
call "/input?buttons=X+Y&ms=300"
call "/input?buttons=L+R+ZL+ZR&ms=400"
call "/input?buttons=A+B+X+Y+UP&ms=500"

echo "[4/5] combo sequence"
call "/sequence?steps=L:120>R:120>L:120>R:120>B:120>A:120>B:120>A:120&gap=50&repeat=0"
sleep 1.2
call "/sequence?steps=UP:100>RIGHT:100>DOWN:100>LEFT:100&gap=40&repeat=1"
sleep 1.0

echo "[5/5] cleanup"
call "/release"
call "/auto"

echo
echo "Done."
