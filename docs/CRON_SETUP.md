# Jobs & Cron Setup — ContaNeta

## Overview

Two job systems handle background work:

| System | Table | Worker | Purpose |
|--------|-------|--------|---------|
| Generic Jobs | `jobs` | `worker.py` | General-purpose queue (future handlers) |
| SAT Sync | `sat_jobs` | `scripts/sat_worker.py` | SAT CFDI sync via PHP subprocess |

Both use SQLite WAL mode for concurrent reads during writes.

---

## Generic Job Queue (`jobs` table)

### Architecture

```
Portal/API                    jobs table                worker.py
───────────                  ──────────                ─────────
enqueue_job()  ──INSERT──►   status=queued  ──claim──►  handler(job, ctx)
                              ↓ (lease lock)              │
                             status=running               │
                              ↓                           ▼
                             status=success/failed    complete/fail_job()
```

### Features

| Feature | Implementation |
|---------|---------------|
| Deduplication | SHA-256 hash of `issuer_id\|name\|payload_json` |
| Lease locking | `locked_by` + `locked_at` with configurable lease (default 900s) |
| Stale lock recovery | Auto-requeue if `locked_at` exceeds lease timeout |
| Retries | Configurable `max_attempts` (1-20, default 3) |
| Backoff | Exponential with jitter: `min(600, 2^attempts + random(0, min(10, base)))` |
| Timeout | SIGALRM-based per-job timeout (default 60s) |
| Transaction safety | `BEGIN IMMEDIATE` for atomic claim |

### Usage

```python
from services.jobs import enqueue_job

# Enqueue a job (returns existing ID if duplicate is active)
job_id = enqueue_job(
    name="my_task",
    issuer_id=42,
    payload={"key": "value"},
    max_attempts=3,
    run_after="2024-01-15 10:00:00",  # optional: delay execution
)
```

### Worker Commands

```bash
# Process one job and exit
python worker.py --once

# Continuous loop (polls every 1s when idle)
python worker.py --loop --sleep 1.0

# With custom settings
python worker.py --loop \
  --worker-id worker-1 \
  --lease-seconds 900 \
  --timeout-seconds 60
```

### Adding Handlers

Register handlers in `worker.py:_load_handlers()`:

```python
def _load_handlers() -> dict[str, JobHandler]:
    return {
        "my_task": handle_my_task,
    }

def handle_my_task(job: dict, ctx: JobContext) -> dict:
    ctx.progress(50, "Processing...")
    # do work
    return {"processed": True}
```

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `WORKER_ID` | `worker-1` | Identifier for lease ownership |
| `JOB_LEASE_SECONDS` | `900` | Lock expiry (15 min) |
| `JOB_TIMEOUT_SECONDS` | `60` | Per-job execution timeout |
| `APP_DB_PATH` | `./invoicing.db` | Database path |

---

## SAT Sync Jobs (`sat_jobs` table)

### Architecture

```
Portal (trigger sync)         sat_jobs table            sat_worker.py
─────────────────────        ──────────────            ──────────────
INSERT 2 rows  ──────►       status=queued  ──fetch──►  run_sync_php()
(issued + received)            ↓                          │
                              status=running              │ decrypted_fiel_env()
                               ↓                          │ → PHP sync.php
                              status=ok/error             ▼
                                                       mark_done()
```

### Table Schema

```sql
CREATE TABLE sat_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  job_type TEXT NOT NULL CHECK(job_type IN ('metadata','xml','parse')),
  direction TEXT CHECK(direction IN ('issued','received')),
  window_from TEXT,
  window_to TEXT,
  status TEXT NOT NULL DEFAULT 'queued'
    CHECK(status IN ('queued','running','ok','error')),
  attempts INTEGER NOT NULL DEFAULT 0,
  locked_at TEXT,
  started_at TEXT,
  finished_at TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
);
```

### Worker Commands

```bash
# Process queued SAT jobs (run from project root)
python scripts/sat_worker.py

# Or with explicit DB path
APP_DB_PATH=/path/to/invoicing.db python scripts/sat_worker.py
```

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `APP_DB_PATH` | `./invoicing.db` | Database path |
| `PHP_BIN` | `php` | PHP binary path |
| `SAT_SYNC_BACKFILL_DAYS` | `7` | Days to look back for sync |
| `SAT_SYNC_WINDOW_HOURS` | `6` | Window size for time-based sync |

---

## Cron Script (`sat_sync/cron_sat_sync.sh`)

Full SAT sync pipeline that runs independently of the job queue. Processes **all issuers** with `sat_credentials`.

### Pipeline Steps

```
1. METADATA  — sync.php (metadata list: total, fecha, estado)
2. XML       — sync_xml.php (create XML download requests)
3. VERIFY    — verify_requests.php (download ready packages)
4. PARSE     — parse_xml.php (extract subtotal, IVA, dates)
5. BACKFILL  — backfill_clients_from_sat.py (populate clients table)
6. CANCEL    — check_cancellations.php (update cancellation status)
```

### Crontab Setup

```crontab
# SAT sync every 15 minutes
*/15 * * * * /path/to/project/sat_sync/cron_sat_sync.sh >> /tmp/sat_sync.log 2>&1

# SAT job queue worker every 5 minutes
*/5 * * * * cd /path/to/project && python scripts/sat_worker.py >> /tmp/sat_worker.log 2>&1

# Generic job worker (if using generic queue)
# Option A: cron (every minute)
* * * * * cd /path/to/project && python worker.py --once >> /tmp/worker.log 2>&1
# Option B: systemd service (continuous)
# See deploy/conta-worker.service
```

### Systemd Service (Generic Worker)

```ini
# /etc/systemd/system/conta-worker.service
[Unit]
Description=ContaNeta Job Worker
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/project
ExecStart=/path/to/project/.venv/bin/python worker.py --loop --sleep 2.0
Restart=always
RestartSec=5
Environment=APP_DB_PATH=/path/to/invoicing.db
Environment=WORKER_ID=worker-1

[Install]
WantedBy=multi-user.target
```

---

## Monitoring

### Check Job Status (SQLite)

```bash
# Generic jobs: pending/running
sqlite3 invoicing.db "SELECT id, name, status, attempts, message FROM jobs WHERE status IN ('queued','running') ORDER BY id;"

# SAT jobs: pending/running
sqlite3 invoicing.db "SELECT id, issuer_id, job_type, direction, status, attempts FROM sat_jobs WHERE status IN ('queued','running') ORDER BY id;"

# Failed jobs (last 10)
sqlite3 invoicing.db "SELECT id, name, attempts, max_attempts, message FROM jobs WHERE status = 'failed' ORDER BY updated_at DESC LIMIT 10;"

# SAT job errors (last 10)
sqlite3 invoicing.db "SELECT id, issuer_id, direction, last_error, finished_at FROM sat_jobs WHERE status = 'error' ORDER BY finished_at DESC LIMIT 10;"
```

### Admin Dashboard

The admin panel (`/admin/`) shows:
- Recent SAT jobs with status, timestamps, and errors
- Pending job count in the dashboard summary

### Health Check

```bash
# Via smoke script
bash scripts/smoke_release.sh
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Jobs stuck in `running` | Worker crashed mid-job | Generic: auto-recovers via lease expiry. SAT: manually update `SET status='queued'` |
| Duplicate jobs created | Race condition on insert | Generic: SHA-256 dedup handles this. SAT: check before INSERT |
| SAT sync timeout | SAT servers slow | Increase `SAT_SYNC_WINDOW_HOURS` or PHP timeout |
| `No hay sat_credentials` | FIEL not uploaded | Upload FIEL in Settings > FIEL |
| Worker exits immediately | No jobs in queue | Expected behavior for `--once` mode |
| PHP not found | `PHP_BIN` not set | Set `PHP_BIN=/usr/bin/php` in env |
