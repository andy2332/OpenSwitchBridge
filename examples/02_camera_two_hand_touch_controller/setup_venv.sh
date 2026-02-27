#!/usr/bin/env bash
set -euo pipefail

python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt

echo "[INFO] venv ready: $(pwd)/.venv"
