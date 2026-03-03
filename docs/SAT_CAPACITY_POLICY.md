# SAT Capacity Policy — Anti-Colapso

## Problem

The SAT (Mexico's tax authority) has rate limits and availability windows. Flooding it with sync requests can:
- Get our IP temporarily blocked
- Cause cascading timeouts that fill the job queue
- Waste resources on jobs that will fail anyway

## Rate Limits

| Limit | Value | Where enforced |
|-------|-------|----------------|
| **Global jobs/hour** | 60 | `enqueue_sat_sync()` in `sat_autosync.py` |
| **Per-issuer jobs/day** | 10 | `enqueue_sat_sync()` in `sat_autosync.py` |
| **Dedupe window** | 2 hours | Same issuer+direction won't re-enqueue if queued/running |
| **Success cooldown** | 8 hours | After successful sync, issuer skipped for 8h |

## Exponential Backoff on Error

When a SAT sync fails, the cooldown increases with consecutive failures:

| Consecutive failures | Cooldown | Rationale |
|---------------------|----------|-----------|
| 1 | 30 minutes | Transient error, retry soon |
| 2 | 2 hours | Likely a real issue, back off |
| 3+ | 24 hours | Persistent problem, needs investigation |

The backoff resets to 0 after a successful sync.

**Implementation**: `_backoff_minutes()` + `_consecutive_failures()` in `services/sat_autosync.py`, called from `update_sync_state_after_job()`.

## How It Works

```
1. Scheduler runs (cron or systemd timer)
2. get_eligible_issuers() → filters by:
   - Valid FIEL credentials (validation_ok=1)
   - Active issuer (active=1)
   - Recent activity (login or subscription within active_days)
   - Cooldown expired
   - No queued/running jobs
3. enqueue_sat_sync() → checks:
   - Dedupe: recent job for same issuer+direction?
   - Global rate: < 60 jobs in last hour?
   - Per-issuer rate: < 10 jobs in last 24h?
4. sat_worker picks up job → runs sync.php
5. update_sync_state_after_job() →
   - Success: cooldown = 8 hours
   - Error: cooldown = backoff(consecutive_failures)
```

## Admin Visibility

- **`/admin/sat-jobs`**: Filter by status, see error counts
- **`/admin/sat-jobs/{id}`**: Cooldown badge on sync state (yellow when active)
- **`/admin/issuers/{id}`**: SAT badge (OK/ERROR/NO CONFIG), sync dates, failed jobs 24h
- **`/admin/dashboard`**: SAT jobs 24h summary cards

## Tuning

All limits are constants in `services/sat_autosync.py`:

```python
MAX_JOBS_PER_HOUR = 60
MAX_JOBS_PER_ISSUER_PER_DAY = 10
BACKOFF_SCHEDULE_MINUTES = [30, 120, 1440]  # 30min, 2h, 24h
DEDUPE_WINDOW_HOURS = 2
```

To adjust: edit constants and restart the scheduler/worker. No migration needed.

## Manual Overrides

```bash
# Clear cooldown for a specific issuer
sqlite3 /var/lib/contaneta/invoicing.db \
  "UPDATE sat_sync_state SET cooldown_until=NULL WHERE issuer_id=123;"

# Clear all cooldowns (emergency)
sqlite3 /var/lib/contaneta/invoicing.db \
  "UPDATE sat_sync_state SET cooldown_until=NULL;"

# Reset stuck jobs
sqlite3 /var/lib/contaneta/invoicing.db \
  "UPDATE sat_jobs SET status='queued', locked_at=NULL WHERE status='running' AND locked_at < datetime('now', '-30 minutes');"

# Or use the admin UI: /admin/sat-jobs/{id} → Re-encolar
```
