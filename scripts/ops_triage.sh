#!/usr/bin/env bash
# ops_triage.sh — Quick diagnostic snapshot for ContaNeta production issues.
# Usage: bash scripts/ops_triage.sh [db_path]
# Outputs a summary of system health, recent errors, stuck jobs, and disk usage.
set -euo pipefail

DB="${1:-${APP_DB_PATH:-./invoicing.db}}"
LOG_DIR="${LOG_DIR:-/var/log/contaneta}"

echo "===== ContaNeta Ops Triage — $(date -u '+%Y-%m-%d %H:%M:%S UTC') ====="
echo ""

# 1. Services status (if systemd)
echo "--- Services ---"
for svc in contaneta-web contaneta-worker contaneta-sat-scheduler; do
    if systemctl is-active "$svc" &>/dev/null 2>&1; then
        status=$(systemctl is-active "$svc" 2>/dev/null || echo "unknown")
        echo "  $svc: $status"
    fi
done
echo ""

# 2. Database health
echo "--- Database ---"
if [ -f "$DB" ]; then
    size=$(du -h "$DB" 2>/dev/null | cut -f1)
    echo "  Path: $DB ($size)"
    # WAL size
    if [ -f "${DB}-wal" ]; then
        wal_size=$(du -h "${DB}-wal" 2>/dev/null | cut -f1)
        echo "  WAL: ${DB}-wal ($wal_size)"
    fi
    # Quick integrity check (fast)
    if command -v sqlite3 &>/dev/null; then
        integrity=$(sqlite3 "$DB" "PRAGMA quick_check;" 2>/dev/null || echo "FAILED")
        echo "  Integrity: $integrity"
        # Migration version
        migration=$(sqlite3 "$DB" "SELECT MAX(version) FROM schema_migrations;" 2>/dev/null || echo "?")
        echo "  Migration version: $migration"
    else
        echo "  (sqlite3 CLI not found — skip DB checks)"
    fi
else
    echo "  WARNING: Database not found at $DB"
fi
echo ""

# 3. Recent errors (last 24h)
echo "--- Errors (last 24h) ---"
if [ -f "$DB" ] && command -v sqlite3 &>/dev/null; then
    error_count=$(sqlite3 "$DB" "SELECT COUNT(*) FROM error_events WHERE created_at > datetime('now', '-24 hours');" 2>/dev/null || echo "?")
    echo "  Error events (24h): $error_count"
    if [ "$error_count" != "0" ] && [ "$error_count" != "?" ]; then
        echo "  Latest:"
        sqlite3 -header -column "$DB" \
            "SELECT id, substr(created_at,1,19) AS time, status, method||' '||substr(path,1,40) AS route, substr(message_internal,1,60) AS message FROM error_events WHERE created_at > datetime('now', '-24 hours') ORDER BY id DESC LIMIT 5;" 2>/dev/null || true
    fi
else
    echo "  (skipped — no DB or sqlite3)"
fi
echo ""

# 4. Job queue status
echo "--- Jobs ---"
if [ -f "$DB" ] && command -v sqlite3 &>/dev/null; then
    sqlite3 -header -column "$DB" \
        "SELECT status, COUNT(*) AS count FROM jobs GROUP BY status;" 2>/dev/null || echo "  (jobs table not found)"
    echo ""
    # Stuck jobs (running > 30 min)
    stuck=$(sqlite3 "$DB" "SELECT COUNT(*) FROM jobs WHERE status = 'running' AND locked_at < datetime('now', '-30 minutes');" 2>/dev/null || echo "?")
    if [ "$stuck" != "0" ] && [ "$stuck" != "?" ]; then
        echo "  WARNING: $stuck stuck jobs (running > 30 min)"
    fi
fi
echo ""

# 5. SAT jobs status
echo "--- SAT Jobs ---"
if [ -f "$DB" ] && command -v sqlite3 &>/dev/null; then
    sqlite3 -header -column "$DB" \
        "SELECT status, COUNT(*) AS count FROM sat_jobs GROUP BY status;" 2>/dev/null || echo "  (sat_jobs table not found)"
    echo ""
    sat_stuck=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sat_jobs WHERE status = 'running' AND locked_at < datetime('now', '-30 minutes');" 2>/dev/null || echo "?")
    if [ "$sat_stuck" != "0" ] && [ "$sat_stuck" != "?" ]; then
        echo "  WARNING: $sat_stuck stuck SAT jobs (running > 30 min)"
    fi
    # Cooldowns active
    cooldown=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sat_sync_state WHERE cooldown_until > datetime('now');" 2>/dev/null || echo "?")
    echo "  Active cooldowns: $cooldown"
fi
echo ""

# 6. Disk usage
echo "--- Disk ---"
if [ -d "/var/lib/contaneta" ]; then
    du -sh /var/lib/contaneta 2>/dev/null || true
    du -sh /var/lib/contaneta/storage 2>/dev/null || true
fi
if [ -d "/var/backups/contaneta" ]; then
    du -sh /var/backups/contaneta 2>/dev/null || true
    backup_count=$(ls -1 /var/backups/contaneta/*.zip 2>/dev/null | wc -l || echo 0)
    echo "  Backup files: $backup_count"
fi
df -h / 2>/dev/null | tail -1 | awk '{print "  Root disk: " $3 " used / " $2 " (" $5 " full)"}'
echo ""

# 7. Recent log errors
echo "--- Recent Log Errors ---"
if [ -d "$LOG_DIR" ]; then
    for log in "$LOG_DIR"/web.log "$LOG_DIR"/worker.log; do
        if [ -f "$log" ]; then
            err_lines=$(tail -200 "$log" 2>/dev/null | grep -ci "error\|exception\|traceback" || echo 0)
            echo "  $(basename "$log"): $err_lines error lines (last 200)"
        fi
    done
else
    echo "  (log dir $LOG_DIR not found)"
fi
echo ""

# 8. App health endpoint
echo "--- Health Check ---"
if command -v curl &>/dev/null; then
    health=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://localhost:8000/health 2>/dev/null || echo "unreachable")
    echo "  /health: $health"
else
    echo "  (curl not found)"
fi

echo ""
echo "===== Triage complete ====="
