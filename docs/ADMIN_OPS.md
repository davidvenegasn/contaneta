# Admin Operations Center

The admin dashboard (`/admin` or `/admin/dashboard`) serves as the operations center for ContaNeta.

## What you see

### KPI Row
- **Usuarios / Activos** — total users and those with at least one membership
- **Issuers** — total registered companies
- **Jobs en cola** — queued + running background jobs
- **Jobs fallidos hoy** — failed jobs today (red highlight if > 0)
- **Errores 5xx hoy** — server errors today (red highlight if > 0)

### SAT Jobs (24h)
Breakdown of SAT sync jobs in the last 24 hours: queued, running, completed, error, and issuers needing review.

### Issuers con problemas SAT
Table of issuers with:
- Active cooldown (exponential backoff after failures)
- Recent SAT job errors (last 24h)

Shows RFC, direction (issued/received), error count, cooldown expiry, and last error message.

### Quick Actions
- **Re-encolar errores SAT recientes** — resets all `error` SAT jobs from the last 24h back to `queued` and clears cooldowns. Requires confirmation.
- Links to: Operations (advanced), Config check, all SAT jobs, all errors

### Last Backup
Shows the most recent database backup file, its size, timestamp, and total backup count. Checks `BACKUP_DIR` env var first, then falls back to local `backup/` directory.

### Recent Errors / Jobs / Logins / Audit
Standard tables showing the latest system activity.

## Available POST actions

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/admin/sat-jobs/requeue-recent-errors` | POST | admin | Re-enqueue error SAT jobs from last 24h, clear cooldowns |
| `/admin/ops` | POST | admin/owner | Migrations, DB verify, backup (see Operations page) |

## Access

Requires admin role (or admin+owner for some endpoints). If `ADMIN_PASSWORD` is set, HTTP Basic Auth is also required.
