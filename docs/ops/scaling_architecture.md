# Scaling & Production Deployment Architecture

**Date:** 2026-05-12

## Current Architecture

```
┌─────────┐     ┌─────────────┐     ┌──────────────────┐     ┌──────────┐
│ Browser │────▶│    Caddy     │────▶│   Gunicorn (1w)  │────▶│  SQLite  │
│         │     │  (TLS,proxy) │     │  + 4 threads     │     │  (WAL)   │
└─────────┘     └─────────────┘     │  uvicorn worker  │     └──────────┘
                                    └──────────────────┘           ▲
                                           ▲                       │
                                    ┌──────┴───────┐     ┌────────┴───────┐
                                    │  worker.py   │     │  sat_sync/     │
                                    │ (single proc)│     │  PHP scripts   │
                                    │  jobs queue  │────▶│  (subprocess)  │
                                    └──────────────┘     └────────────────┘
```

### Key Constraints
- **1 Gunicorn worker** (SQLite single-writer limitation)
- **4 threads** per worker (concurrent reads via WAL)
- No connection pooling (new connection per operation, close after use)
- Worker runs as separate systemd service with lease-based job locking
- Static files mounted via FastAPI (should be served by Caddy in prod)

### Database
- **invoicing.db**: All application data (WAL mode, busy_timeout=30s)
- **catalogs/catalogs.db**: Read-only SAT catalogs
- Per-request connections (no pool)
- Transactions via `BEGIN`/`COMMIT`/`ROLLBACK` context manager

## Target Architecture (1K+ Concurrent Users)

```
┌─────────┐     ┌──────────┐     ┌─────────────────┐     ┌────────────┐
│ Browser │────▶│   CDN    │────▶│  Load Balancer   │     │ PostgreSQL │
│         │     │ (static) │     │ (ALB or Caddy)   │     │   (RDS)    │
└─────────┘     └──────────┘     └────────┬────────┘     └──────┬─────┘
                                          │                      │
                              ┌───────────┼───────────┐          │
                              ▼           ▼           ▼          │
                        ┌──────────┐ ┌──────────┐ ┌──────────┐  │
                        │ uvicorn  │ │ uvicorn  │ │ uvicorn  │──┘
                        │ worker 1 │ │ worker 2 │ │ worker N │
                        └──────────┘ └──────────┘ └──────────┘
                                          │
                              ┌───────────┼───────────┐
                              ▼           ▼           ▼
                        ┌──────────┐ ┌──────────┐ ┌──────────┐
                        │ worker 1 │ │ worker 2 │ │ worker N │
                        │ (jobs)   │ │ (jobs)   │ │ (jobs)   │
                        └──────────┘ └──────────┘ └──────────┘
                                          │
                              ┌───────────┼───────────┐
                              ▼           ▼           ▼
                        ┌──────────┐ ┌──────────┐ ┌──────────┐
                        │  Redis   │ │  Sentry  │ │  S3      │
                        │ (cache)  │ │ (errors) │ │ (backups)│
                        └──────────┘ └──────────┘ └──────────┘
```

## SQLite → PostgreSQL Migration Plan

### When to Migrate
- **> 50 concurrent users**: SQLite write contention becomes noticeable
- **> 100K rows in sat_cfdi**: Index performance degrades for complex queries
- **Multi-server deployment**: SQLite cannot be shared across instances
- **Need for concurrent writes**: Job queue + web writes conflict

### Migration Steps
1. Add `psycopg2-binary` dependency
2. Modify `database.py` to support PG connection string (env: `DATABASE_URL`)
3. Convert migrations to be PG-compatible (most are already standard SQL)
4. Key SQL differences:
   - `AUTOINCREMENT` → `SERIAL` or `GENERATED ALWAYS AS IDENTITY`
   - `datetime('now')` → `NOW()`
   - `PRAGMA` statements → PG configuration
   - `substr()` → `substring()`
5. Dump SQLite data → CSV → PG `COPY`
6. Switch `DATABASE_URL`, deploy, verify

### Tables by Volume (Migration Priority)

| Table | Growth Rate | Migration Priority |
|-------|-------------|-------------------|
| sat_cfdi | 10-100K/issuer | HIGH |
| bank_movements | 1-10K/issuer/month | HIGH |
| jobs | 100s/day | HIGH |
| audit_log | 1K/issuer/month | MEDIUM |
| invoices | 1-10K/issuer | MEDIUM |
| exchange_rates/dof_rates | 100s/year | LOW |
| issuers/users | 10s | LOW |

## AWS Deployment Options

### Option A: EC2 Single-Host (MVP — Current)
```
EC2 t3.medium (2 vCPU, 4 GB RAM)
├── Caddy (reverse proxy, TLS)
├── Gunicorn (1 worker, 4 threads)
├── worker.py (background jobs)
├── SQLite (local SSD)
└── Cron backups → S3
```

**Cost estimate**: ~$35/month (t3.medium reserved)
**Capacity**: ~200 active users
**Pros**: Simple, cheap, easy to manage
**Cons**: Single point of failure, no horizontal scaling

### Option B: ECS Fargate + RDS (Scale)
```
ALB → ECS Fargate
├── Web service (2-4 tasks, 0.5 vCPU, 1 GB each)
├── Worker service (1-2 tasks, 0.5 vCPU, 1 GB each)
├── RDS PostgreSQL (db.t3.micro → db.t3.medium)
├── ElastiCache Redis (cache.t3.micro)
├── S3 (backups, XML storage)
└── CloudWatch (logs, metrics)
```

**Cost estimates**:

| Users | RDS | ECS | Redis | S3 | Total/month |
|-------|-----|-----|-------|-----|-------------|
| 200 | $15 (t3.micro) | $30 (2 tasks) | $13 | $5 | ~$65 |
| 1,000 | $55 (t3.small) | $60 (4 tasks) | $13 | $15 | ~$145 |
| 5,000 | $110 (t3.medium) | $120 (8 tasks) | $25 | $30 | ~$290 |

**Pros**: Auto-scaling, managed DB, zero-downtime deploys
**Cons**: More complex, higher baseline cost

## CI/CD Pipeline (Recommended)

```
GitHub Push → GitHub Actions
  ├── Lint (ruff, mypy)
  ├── Test (pytest -q)
  ├── Build (Docker image)
  ├── Push to ECR
  └── Deploy to ECS (blue/green)
```

### Dockerfile (suggested)
```dockerfile
FROM python:3.14-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["gunicorn", "app:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "2", "-b", "0.0.0.0:8000"]
```

## Backup Strategy

### Current (Single Host)
- **RPO**: 24 hours (daily backups via `backup_nightly.sh`)
- **RTO**: 30-60 minutes (manual restore from backup)
- Retention: 30 days
- SQLite `.backup` command (WAL-safe, atomic)

### Target (Production)
- **RPO**: 1 hour (PG continuous archiving with WAL-G)
- **RTO**: 15 minutes (RDS automated restore from snapshot)
- Retention: 30 days snapshots + 7 days WAL
- Cross-region replication for DR

## Monitoring Stack

### Current
- Sentry (optional, `SENTRY_DSN`)
- `/health`, `/ready` endpoints
- Error events table in SQLite
- Request ID tracking in logs

### Recommended
| Tool | Purpose | Priority |
|------|---------|----------|
| Sentry | Error tracking, performance | HIGH (already supported) |
| CloudWatch | Logs aggregation, alerts | HIGH |
| Prometheus + Grafana | Metrics dashboards | MEDIUM |
| PagerDuty/Opsgenie | On-call alerting | MEDIUM |
| Uptime Robot | External availability | HIGH (free tier) |

### Key Metrics to Monitor
- HTTP 5xx rate
- Response time p95
- SQLite WAL size
- Job queue depth (pending jobs)
- Disk space remaining
- SAT sync success rate
- Active sessions count
