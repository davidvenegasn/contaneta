#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PYTHON_BIN:-python3}"

echo "==> Setup dev (venv + deps + .env)"

if [ ! -d ".venv" ]; then
  echo "==> Creando venv en .venv/"
  "$PY" -m venv .venv
fi

echo "==> Instalando dependencias"
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
if [ -f "requirements-dev.txt" ]; then
  echo "==> Instalando dependencias dev (requirements-dev.txt)"
  .venv/bin/pip install -r requirements-dev.txt
fi

if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    echo "==> Creando .env desde .env.example"
    cp .env.example .env
  elif [ -f "env.example" ]; then
    echo "==> Creando .env desde env.example"
    cp env.example .env
  else
    echo "==> No encontré .env.example. Crea .env manualmente."
  fi
else
  echo "==> .env ya existe (no se modifica)"
fi

echo ""
echo "Listo."
echo "Siguiente:"
echo "  - Iniciar server:  ./run_server.sh"
echo "  - Smoke API:       bash scripts/smoke_api.sh"

