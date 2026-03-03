# SAT Auto-Sync Policy

## Overview

SAT synchronization runs automatically for eligible issuers without user intervention. The scheduler enqueues jobs into the `sat_jobs` table, and the existing `scripts/sat_worker.py` processes them by calling `sat_sync/sync.php`.

## Eligible Issuers

An issuer qualifies for auto-sync when ALL conditions are met:

1. **Active issuer** — `issuers.active = 1`
2. **Valid FIEL** — `sat_credentials.validation_ok = 1`
3. **Cooldown expired** — `sat_sync_state.cooldown_until < now()` or no sync state exists
4. **No recent jobs** — No `sat_jobs` with `status IN ('queued','running')` created in the last 2 hours for that issuer+direction

## Cooldown

- **Default**: 8 hours per issuer/direction
- **Configurable**: `--cooldown-hours` on the scheduler CLI
- **Set on success**: After a successful sync, `cooldown_until = now + cooldown_hours`
- **Not extended on failure**: Failed syncs don't extend cooldown (the scheduler will retry on next run)
- **Onboarding**: Credentials upload triggers immediate sync (no cooldown wait)

## Dedup

Before enqueuing a job, the system checks for an existing `sat_jobs` row with:
- Same `issuer_id` and `direction`
- `status IN ('queued', 'running')`
- `created_at` within the last 2 hours

If found, the enqueue is skipped. This prevents duplicate jobs from multiple scheduler runs or concurrent triggers.

## Batch Size

- **Default**: 50 issuers per scheduler run
- **Configurable**: `--batch` flag
- **Priority**: Issuers with oldest `last_success_at` are scheduled first (least-recently-synced gets priority)

## Backfill Buffer

- **Default**: 7 days (`SAT_SYNC_BACKFILL_DAYS` env var)
- **Onboarding**: Uses default backfill (covers current + previous month effectively)
- **Window**: 6 hours (`SAT_SYNC_WINDOW_HOURS` env var) — the time window for fetching new CFDIs

## What Happens on Failure

1. The worker marks the job as `status='error'` with `last_error` message
2. `sat_sync_state.last_error` is updated
3. Cooldown is NOT extended — the scheduler will re-attempt on its next eligible run
4. Manual retry available via admin panel (`/admin/jobs/{id}` → "Re-encolar")

## Onboarding Auto-Sync

When a user uploads and validates FIEL/CSD credentials:
1. If `validation_ok = True`, the system auto-enqueues 2 jobs:
   - `issued` sync
   - `received` sync
2. Dedup prevents duplicates if the user re-uploads quickly
3. The portal shows the sync status in the topbar chips

## Running in Production

### Scheduler (cron)
```bash
# Every 10 minutes: enqueue eligible issuers
*/10 * * * * cd /path/to/app && .venv/bin/python scripts/sat_scheduler.py --batch 50 --cooldown-hours 8
```

### Worker (cron or systemd)
```bash
# Every 2 minutes: process queued jobs
*/2 * * * * cd /path/to/app && .venv/bin/python scripts/sat_worker.py
```

Or run the worker as a systemd service for lower latency:
```bash
# See deploy/conta-invoicing-worker.service
```

### Dry Run
```bash
python scripts/sat_scheduler.py --dry-run --batch 100
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SAT_SYNC_BACKFILL_DAYS` | 7 | Days to look back for CFDIs |
| `SAT_SYNC_WINDOW_HOURS` | 6 | Hours window for each sync |
| `SAT_SYNC_COOLDOWN_SECONDS` | 21600 (6h) | Cooldown after success (generic worker) |
| `PHP_BIN` | `php` | Path to PHP binary |
