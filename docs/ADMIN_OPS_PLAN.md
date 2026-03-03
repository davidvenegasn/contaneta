# Admin Ops Plan + SAT Auto-Sync Policy

## What Already Exists

### Admin Panel (`routers/admin.py`, 10+ routes)
- Dashboard (`/admin/dashboard`) — stats: users, issuers, jobs, errors, CFDI counts
- Users list (`/admin/users`) — all users with max role
- Issuers list (`/admin/issuers`) — search, plan status, last SAT sync
- Issuer detail (`/admin/issuers/{id}`) — admin notes, needs_review flag
- Jobs list (`/admin/jobs`) — filter by status, issuer_id, name
- Job detail (`/admin/jobs/{id}`) — payload/result JSON
- Errors list (`/admin/errors`) — last 100 error_events
- Error detail (`/admin/errors/{id}`) — internal message + traceback
- Ops panel (`/admin/ops`) — run migrations, verify_db, backup
- Impersonation — start/stop with 4-part session cookie, audit logged

### Jobs Queue (`services/jobs.py`)
- Table: `jobs` with full dedup (SHA-256 payload hash), lease-based locking
- Functions: `enqueue_job`, `claim_next_job`, `complete_job`, `fail_job`
- Retry: exponential backoff (2^attempts + jitter, cap 600s)
- Indices: status, run_after, locked_at, payload_hash, dedup unique partial

### Worker (`worker.py`)
- CLI: `--once` / `--loop` with configurable sleep, lease, timeout
- Claims jobs atomically (BEGIN IMMEDIATE), handles timeouts via SIGALRM
- **Handler registry is empty** — no handlers registered yet

### SAT Worker (`scripts/sat_worker.py`)
- Separate worker operating on `sat_jobs` table (not generic `jobs`)
- Calls `sat_sync/sync.php` with decrypted FIEL env vars
- Status flow: queued → running → ok/error

### SAT Sync State (`sat_sync_state`)
- Columns: issuer_id, direction, last_sync_from, last_sync_to, last_run_at
- **Missing**: last_success_at, last_error, cooldown_until, backfill_days

### Error Events (`error_events`)
- Lazy-created table with request_id, path, status, message, traceback
- Redacted logging (passwords/tokens scrubbed)

---

## What Needs to Be Done

### FASE 1 — Enhance sat_sync_state table
- ADD COLUMN `last_success_at` TEXT
- ADD COLUMN `last_attempt_at` TEXT
- ADD COLUMN `last_error` TEXT
- ADD COLUMN `cooldown_until` TEXT
- ADD COLUMN `backfill_days` INTEGER DEFAULT 2
- ADD COLUMN `updated_at` TEXT

Files: 1 migration file

### FASE 2 — Worker handlers + scheduler
- Register SAT sync handlers in `worker.py` → `_load_handlers()`
- Create `services/sat_job_handlers.py`:
  - `handle_sat_sync_month(job, ctx)` — sync specific month for issuer+direction
  - `handle_sat_refresh_light(job, ctx)` — current month + buffer
  - `handle_sat_verify_credentials(job, ctx)` — validate FIEL
  - Each handler updates `sat_sync_state`
- Add scheduler function (called in worker --loop):
  - Query eligible issuers (valid FIEL, cooldown expired, recent login)
  - Enqueue `sat_refresh_light` jobs with dedup protection
  - Default cooldown: 6-12 hours per issuer

Files: worker.py, services/sat_job_handlers.py (new), services/sat_sync.py

### FASE 3 — Auto-sync on credentials upload
- In `routers/portal.py` after FIEL validation OK:
  - Enqueue 4 jobs: issued+received × current+previous month
  - Set `sat_sync_state.cooldown_until` to prevent immediate re-sync

Files: routers/portal.py

### FASE 4 — Admin actions (enhancements)
- Add requeue action to `/admin/jobs/{id}` (POST)
- Add force-sync button to `/admin/issuers/{id}` (enqueues sat_refresh_light)
- Show SAT sync status more prominently on issuer detail

Files: routers/admin.py, templates/admin_issuer_detail.html, templates/admin_job_detail.html

### FASE 5 — Documentation
- docs/ADMIN_RUNBOOK.md
- docs/SAT_AUTOSYNC_POLICY.md
- docs/OPS_RUNBOOK.md updates

---

## Files to Touch (by phase)

| Phase | Files (max) |
|-------|-------------|
| 1 | migrations/034_*.sql |
| 2 | worker.py, services/sat_job_handlers.py (new), services/sat_sync.py |
| 3 | routers/portal.py |
| 4 | routers/admin.py, templates/admin_issuer_detail.html, templates/admin_job_detail.html |
| 5 | docs/ADMIN_RUNBOOK.md, docs/SAT_AUTOSYNC_POLICY.md, docs/OPS_RUNBOOK.md |
