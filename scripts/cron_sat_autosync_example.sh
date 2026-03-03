#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# SAT Auto-Sync cron examples
#
# Add to crontab with: crontab -e
# ──────────────────────────────────────────────────────────────

APP_DIR="/opt/contaneta"
VENV="$APP_DIR/.venv/bin/python"
LOG_DIR="$APP_DIR/logs"

# ── Scheduler: enqueue eligible issuers every 10 minutes ─────
# */10 * * * * cd $APP_DIR && $VENV scripts/sat_scheduler.py --batch-size 50 --cooldown-hours 8 --active-days 30 >> $LOG_DIR/sat_scheduler.log 2>&1

# ── Worker: process queued sat_jobs every 2 minutes ──────────
# */2 * * * * cd $APP_DIR && $VENV scripts/sat_worker.py >> $LOG_DIR/sat_worker.log 2>&1

# ── Alternative: run generic worker in loop mode (systemd preferred) ──
# $VENV worker.py --loop --sleep 2 --timeout-seconds 600 --lease-seconds 900

# ── Dry run (test without enqueuing): ────────────────────────
# cd $APP_DIR && $VENV scripts/sat_scheduler.py --dry-run --batch-size 100
