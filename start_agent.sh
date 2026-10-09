#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"
if [[ -x .venv/bin/python ]]; then PYTHON="$(pwd)/.venv/bin/python"; fi
"$PYTHON" main_pc_l9.py --preflight
"$PYTHON" main_pc_l9.py --steps 20 --dashboard
