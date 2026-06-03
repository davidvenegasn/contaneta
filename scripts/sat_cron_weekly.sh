#!/bin/bash
# ────────────────────────────────────────────────────────────────
# sat_cron_weekly.sh — Backfill profundo: últimos 6 meses.
# Corre 1 vez a la semana (domingo 4am). Paranoia.
# ────────────────────────────────────────────────────────────────
set -e
cd "$(dirname "$0")/.."
.venv/bin/python -c "
from services.sat.sat_autosync import enqueue_active_issuers_last_6_months
n = enqueue_active_issuers_last_6_months()
print(f'Encolados {n} sat_jobs para 6 meses')
"
