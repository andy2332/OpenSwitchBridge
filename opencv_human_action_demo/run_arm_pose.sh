#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -d ".venv" ]]; then
  echo "[ERROR] .venv not found in $SCRIPT_DIR"
  echo "[INFO] Create env first:"
  echo "       python3.11 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

source .venv/bin/activate

DEFAULT_ARGS=(
  --backend tasks
  --task-model pose_landmarker_full.task
  --source 0
  --set-res 1280x720
)

if [[ $# -eq 0 ]]; then
  echo "[INFO] No extra args provided, using defaults: ${DEFAULT_ARGS[*]}"
  exec python arm_pose_demo.py "${DEFAULT_ARGS[@]}"
else
  echo "[INFO] Using user args: $*"
  exec python arm_pose_demo.py "$@"
fi
