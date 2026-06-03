#!/bin/bash
# ────────────────────────────────────────────────────────────────
# sat_cron_hourly.sh — Sync INCREMENTAL del mes actual.
# Corre cada hora. Pequeño y rápido.
# ────────────────────────────────────────────────────────────────
set -e
cd "$(dirname "$0")/.."
.venv/bin/python -c "
from services.sat.sat_autosync import enqueue_active_issuers_current_month
n = enqueue_active_issuers_current_month()
print(f'Encolados {n} sat_jobs para mes actual')
"
