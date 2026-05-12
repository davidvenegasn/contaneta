# Monitoring & Error Tracking — ContaNeta

## Health Endpoints

| Endpoint | Purpose | Expected |
|----------|---------|----------|
| `GET /health` | Liveness | `200 {"status":"ok"}` |
| `GET /ready` | Readiness (DB writable) | `200` or `503` |
| `GET /status` | Diagnostics (HTML) | `200` |

## Log Sources

### Application Logs
- **Location**: stdout (systemd captures to journal) or `--access-logfile` / `--error-logfile`
- **Format**: Python logging with `request_id` in each entry
- **Key loggers**: `services.sat`, `services.billing`, `routers.api`, `worker`

### Access Logs
- **Gunicorn**: `--access-logfile /var/log/contaneta/access.log`
- **Nginx**: `/var/log/nginx/access.log`

### Worker Logs
- **Systemd**: `journalctl -u contaneta-worker -f`
- **Job failures**: Logged in `jobs` table (`status='failed'`, `message` column)

## Recommended Monitoring Stack

### Option A: Sentry (Recommended for <500 Users)

```bash
pip install sentry-sdk[fastapi]
```

```python
# app.py startup
import sentry_sdk
sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    traces_sample_rate=0.1,
    environment=os.getenv("ENV", "dev"),
)
```

Free tier covers 5K errors/month. Tracks: unhandled exceptions, slow transactions, release tracking.

### Option B: CloudWatch (If on AWS)

1. Install CloudWatch agent on EC2
2. Stream `/var/log/contaneta/*.log` to CloudWatch Logs
3. Create alarms for:
   - Health check failures (5xx on /health)
   - Error rate >1% over 5 minutes
   - Disk usage >80%
   - CPU >90% sustained 5 minutes

### Option C: Self-hosted (Lightweight)

```bash
# Cron-based health check
*/5 * * * * curl -sf http://localhost:8000/health || echo "ALERT: ContaNeta down at $(date)" >> /var/log/contaneta/alerts.log

# Disk usage check
0 */6 * * * df -h /opt/contaneta | awk 'NR==2{if($5+0>80) print "DISK WARNING: "$5" used"}' >> /var/log/contaneta/alerts.log
```

## Key Metrics to Track

| Metric | Source | Alert Threshold |
|--------|--------|----------------|
| Response time (p95) | Nginx/Sentry | >2s |
| Error rate (5xx) | Access logs | >1% |
| Health check | /health | Any non-200 |
| Worker queue depth | `SELECT COUNT(*) FROM jobs WHERE status='queued'` | >50 |
| DB file size | `ls -la invoicing.db` | >1 GB |
| Disk space | `df -h` | >80% |
| SAT sync failures | `jobs` table, status='failed' AND name LIKE 'sat%' | Any |
| Stripe webhook failures | Application logs | Any |

## Alerting

### Critical (Page immediately)
- Health check down for >2 minutes
- 5xx error rate >5%
- Disk >90%
- Worker not processing jobs for >30 minutes

### Warning (Notify within 1 hour)
- Response time p95 >3s
- DB file >500 MB
- Failed SAT sync job
- Stripe webhook returning errors

### Info (Daily digest)
- New user registrations
- Invoices created
- SAT sync completed counts

## Dashboard Queries (SQLite)

```sql
-- Active users (last 7 days)
SELECT COUNT(DISTINCT user_id) FROM audit_log
WHERE created_at > datetime('now', '-7 days');

-- Job queue health
SELECT status, COUNT(*) FROM jobs
GROUP BY status;

-- Recent errors
SELECT action, COUNT(*) FROM audit_log
WHERE action LIKE '%error%' AND created_at > datetime('now', '-24 hours')
GROUP BY action;

-- SAT sync status
SELECT direction, status, COUNT(*) FROM sat_sync_state
GROUP BY direction, status;
```

## Incident Response

1. **Check health**: `curl http://localhost:8000/health`
2. **Check logs**: `journalctl -u contaneta -n 100 --no-pager`
3. **Check worker**: `journalctl -u contaneta-worker -n 50 --no-pager`
4. **Check DB**: `sqlite3 invoicing.db "PRAGMA integrity_check;"`
5. **Restart if needed**: `sudo systemctl restart contaneta contaneta-worker`
6. **Verify recovery**: `curl http://localhost:8000/health && curl http://localhost:8000/ready`
