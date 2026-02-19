#!/usr/bin/env bash
#
# Arranca el portal para que otras personas puedan abrirlo con un enlace.
# Por defecto escucha en 0.0.0.0 (todas las interfaces) y puerto 8000.
#
# Uso:
#   ./run_server.sh              # puerto 8000
#   ./run_server.sh 5000         # puerto 5000
#
# Luego:
#   - En la misma red (WiFi):  http://TU_IP:8000/portal/home?token=TU_TOKEN
#   - En internet: usa un túnel (ngrok, etc.) — ver COMO_COMPARTIR_LINK.md

set -e
cd "$(dirname "$0")"
PORT="${1:-8000}"

echo "Iniciando portal en http://0.0.0.0:${PORT}"
echo "Para que otros abran con un link:"
# IP local (Mac: en0/en1, Linux: suele ser la primera de hostname -I)
MYIP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || (hostname -I 2>/dev/null | awk '{print $1}') || echo "TU_IP")
echo "  - Misma red:  http://${MYIP}:${PORT}/portal/home?token=TU_TOKEN"
echo "  - Internet:   ver COMO_COMPARTIR_LINK.md"
echo ""

# Usar el Python del venv del proyecto si existe (ahí está uvicorn)
# --reload: reinicia solo al cambiar .py (así se cargan rutas nuevas sin reiniciar a mano)
if [ -x ".venv/bin/python" ]; then
  exec .venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port "$PORT" --reload
else
  exec python3 -m uvicorn app:app --host 0.0.0.0 --port "$PORT" --reload
fi
