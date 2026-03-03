# Admin Runbook

## Accessing the Admin Panel

1. Navigate to `/admin` (requires login + admin role)
2. If `ADMIN_PASSWORD` env var is set, HTTP Basic Auth is also required
3. The `owner` role can view most pages; `admin` role is required for impersonation and write actions

## Common Tasks

### User says "I don't see my invoices"

1. Go to `/admin/issuers` and search by RFC or email
2. Click the issuer to see detail
3. Check SAT sync status (look at `sat_sync_state` last_success_at)
4. If no recent sync: click **"Forzar sync SAT"** button
5. If credentials missing/invalid: impersonate and check `/portal/config/sat`

### Force SAT sync for an issuer

1. Go to `/admin/issuers/{issuer_id}`
2. Click **"Forzar sync SAT"**
3. This enqueues `sat_jobs` for `issued` and `received` directions
4. Wait for `scripts/sat_worker.py` to process (check `/admin/jobs` or `sat_jobs` table)

### Re-enqueue a failed job

1. Go to `/admin/jobs` and filter by status=failed
2. Click the job to see detail (payload, error message)
3. Click **"Re-encolar"** to set status back to `queued`
4. The worker will pick it up on the next run

### Impersonate a user for debugging

1. Go to `/admin/issuers/{id}` and click **"Impersonar este issuer"**
2. You'll see the portal as that user
3. Use the topbar "Dejar de impersonar" button to return to your session
4. All actions during impersonation are logged to `audit_log`

### Check errors by request_id

1. User reports an error with a request ID (shown on error pages)
2. Go to `/admin/errors` and search for the request_id
3. Click to see the full traceback and internal message

### Check SAT sync health

```bash
# Summary of sync state per issuer
sqlite3 invoicing.db "
  SELECT ss.issuer_id, i.rfc, ss.direction,
         ss.last_success_at, ss.last_error, ss.cooldown_until
  FROM sat_sync_state ss
  JOIN issuers i ON i.id = ss.issuer_id
  ORDER BY ss.last_success_at DESC
  LIMIT 20;
"

# Pending SAT jobs
sqlite3 invoicing.db "
  SELECT id, issuer_id, direction, status, created_at
  FROM sat_jobs
  WHERE status IN ('queued','running')
  ORDER BY id;
"
```

### Run the auto-sync scheduler manually

```bash
# Preview what would be enqueued
python scripts/sat_scheduler.py --dry-run --batch 100

# Actually enqueue
python scripts/sat_scheduler.py --batch 50 --cooldown-hours 8
```

## Admin Action Audit

All admin actions are logged to:
- `audit_log` table (DB) — impersonate, force-sync, requeue, notes update
- `action_log` (stderr) — structured one-line events with request_id

Query recent admin actions:
```bash
sqlite3 invoicing.db "
  SELECT created_at, action, user_id, entity, entity_id, details
  FROM audit_log
  WHERE action LIKE 'admin_%' OR action LIKE 'impersonate_%'
  ORDER BY created_at DESC
  LIMIT 20;
"
```
