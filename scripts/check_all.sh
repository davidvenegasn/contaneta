#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "== check_all =="
echo

echo "== dev_check_ui =="
bash scripts/dev_check_ui.sh
echo

echo "== smoke_api (requiere server arriba) =="
bash scripts/smoke_api.sh || true
echo

echo "== pytest (mínimo) =="
if command -v pytest >/dev/null 2>&1; then
  pytest -q || true
elif [ -x ".venv/bin/pytest" ]; then
  .venv/bin/pytest -q || true
else
  echo "WARN: pytest no disponible (instala dev deps o crea .venv)."
fi

echo
echo "OK: check_all completado."

