#!/bin/bash
# ────────────────────────────────────────────────────────────────
# sat_cron_daily.sh — Sync de los últimos 3 meses.
# Corre 1 vez al día (3am). Catch-up para meses anteriores.
# ────────────────────────────────────────────────────────────────
set -e
cd "$(dirname "$0")/.."
.venv/bin/python -c "
from services.sat.sat_autosync import enqueue_active_issuers_last_3_months
n = enqueue_active_issuers_last_3_months()
print(f'Encolados {n} sat_jobs para 3 meses recientes')
"
