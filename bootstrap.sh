#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo 'Установите Python 3.11+ через менеджер пакетов ОС; автоматической установки нет.'
    exit 1
fi
"$PYTHON" -m bootstrap.bootstrap --report
printf '\nДля создания окружения с подтверждением: %s -m bootstrap.bootstrap --create-venv\n' "$PYTHON"
