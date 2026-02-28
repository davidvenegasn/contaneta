#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "== check_all =="
echo

echo "== dev_check_ui =="
bash scripts/dev_check_ui.sh
echo

echo "== smoke_api =="
BASE_URL="${SMOKE_BASE_URL:-http://127.0.0.1:${PORT:-8000}}"

server_started=0
server_pid=""
goto_pytest=0

cleanup_server() {
  if [ "${server_started}" = "1" ] && [ -n "${server_pid}" ]; then
    kill "${server_pid}" >/dev/null 2>&1 || true
    wait "${server_pid}" >/dev/null 2>&1 || true
  fi
}
trap cleanup_server EXIT

if curl -fsS "${BASE_URL}/health" >/dev/null 2>&1; then
  echo "OK: server detectado en ${BASE_URL}"
elif [ "${START_SERVER:-0}" = "1" ]; then
  echo "INFO: levantando server temporal..."
  uvicorn app:app --host 127.0.0.1 --port "${PORT:-8000}" >/tmp/contaneta_check_all_server.log 2>&1 &
  server_pid="$!"
  server_started=1
  for _i in $(seq 1 40); do
    if curl -fsS "${BASE_URL}/health" >/dev/null 2>&1; then
      break
    fi
    sleep 0.5
  done
  if ! curl -fsS "${BASE_URL}/health" >/dev/null 2>&1; then
    echo "ERROR: server no respondió en ${BASE_URL} (ver /tmp/contaneta_check_all_server.log)"
    exit 1
  fi
  echo "OK: server arriba en ${BASE_URL}"
else
  echo "WARN: server no detectado en ${BASE_URL}. Para correr smoke_api:"
  echo "  START_SERVER=1 bash scripts/check_all.sh"
  echo "  # o levanta el server en otra terminal y reintenta"
  echo
  echo "SKIP: smoke_api"
  goto_pytest=1
fi

if [ "${goto_pytest}" = "0" ]; then
  bash scripts/smoke_api.sh
fi
echo

echo "== pytest (mínimo) =="
if command -v pytest >/dev/null 2>&1; then
  pytest -q
elif [ -x ".venv/bin/pytest" ]; then
  .venv/bin/pytest -q
else
  echo "WARN: pytest no disponible (instala dev deps o crea .venv)."
fi

echo
echo "OK: check_all completado."

