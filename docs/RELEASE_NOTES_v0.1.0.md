# Release Notes — v0.1.0

**Date**: 2026-03-03
**Branch**: `release-prep-20260303` → `main`
**Commits**: 14

## Features

### SAT AutoSync PRO
- Automatic scheduler with batch processing, cooldown, and activity filtering
- Onboarding auto-sync: triggers issued+received sync on FIEL upload
- Dedupe: no duplicate jobs within 2-hour window
- Policy documented in `docs/SAT_AUTOSYNC_POLICY.md`

### Admin Ops PRO
- Enhanced dashboard with SAT jobs 24h stats (queued, running, errors, OK)
- Issuers list with SAT badge (OK/ERROR/NO CONFIG), per-direction sync dates, failed jobs 24h
- Issuer detail: credentials status, sync state, recent jobs/errors, bulk requeue
- Dedicated `/admin/sat-jobs` page with status/direction/issuer filters
- Individual SAT job detail with sync state, error display, requeue action
- `/admin/config` page for environment health checks

### Self-Serve SAT Onboarding
- `GET /api/sat/status` — returns credentials, per-direction sync state, recent jobs, pending flag
- SAT sync status card on portal config page with auto-polling (8s while pending, 30s idle)
- Updated success message after credential upload: "Sincronizando tus facturas..."

### SAT Anti-Colapso
- Global rate limit: 60 jobs/hour
- Per-issuer daily limit: 10 jobs/day
- Exponential backoff on error: 30 min → 2 hours → 24 hours cooldown
- Cooldown badge in admin SAT job detail
- Policy documented in `docs/SAT_CAPACITY_POLICY.md`

## Infrastructure

### Production Pack
- Caddy reverse proxy with auto-HTTPS, static files, security headers, 10MB body limit
- `scripts/prod_bootstrap.sh` — full server setup (user, dirs, venv, systemd, logrotate, firewall)
- External data paths: `/var/lib/contaneta/`, `/var/log/contaneta/`, `/var/backups/contaneta/`
- Gunicorn: 1 worker + 4 threads (SQLite constraint)

### Deploy VPS PRO
- 6 systemd units: web, worker, scheduler+timer, backup+timer
- Security hardening: NoNewPrivileges, ProtectSystem=strict, PrivateTmp
- Nginx config with rate limiting
- `deploy/README_DEPLOY.md` — copy-paste deployment guide

### Backups + Restore
- `scripts/backup_nightly.sh` — SQLite online backup + storage tar, 7-day rotation, optional S3
- `scripts/restore_latest.sh` — integrity verification, pre-restore safety copy, service stop/start
- `docs/RECOVERY_PLAYBOOK.md` — 5 scenarios (corruption, deletion, migration, stuck jobs, disaster)

### Observability
- Request ID end-to-end (context var, response header, error events)
- File logging via `LOG_FILE` env var
- Logrotate config for `/var/log/contaneta/`
- Error events on 500 with redaction, admin UI at `/admin/errors`
- `scripts/ops_triage.sh` — diagnostic snapshot (services, DB, errors, jobs, disk)
- Optional Sentry integration (`SENTRY_DSN`)

## Security

- `.gitignore` hardened: `*.db`, `*.sqlite*`, `backups/`
- `safe_export.sh` expanded verification (any .db, backup dirs)
- File upload limits documented per route
- `AT_REST_MASTER_KEY` prod warning in config.py
- `docs/PROD_ENV_CHECKLIST.md`
- Release smoke tests: 22 checks (health, auth enforcement, CSRF, security headers, DB)

## Commits

```
3ba5aae feat: SAT anti-colapso — rate limits, exponential backoff, capacity policy
caf64e8 ops: backup restore script + recovery playbook
814d0d2 ops: observability polish — errors UI, logrotate paths, ops_triage.sh
3817063 ops: prod env hardening — AT_REST_MASTER_KEY warning, /admin/config, checklist
7df8023 security: harden .gitignore, safe_export verification, upload limits docs
aa47562 feat: Self-Serve SAT onboarding — /api/sat/status + sync status UI
4f1d869 feat: Admin Ops — dedicated /admin/sat-jobs with detail, filters, requeue
5427ab3 ops: Production Pack — Caddy, bootstrap, external paths, deploy guide
ea3f12b docs: update release prep status — all jobs completed
a937069 ops: Release Guardrails — smoke tests, Sentry, launch checklist
5510488 ops: Deploy VPS PRO — systemd units, nginx, backups, full guide
76e96aa feat: Admin Ops PRO — dashboard cards, SAT badges, issuer detail, job views
62868d0 feat: SAT AutoSync PRO — scheduler, policy, onboarding, dedupe
0167451 docs: release prep status + admin/autosync planning docs
```

## Known Limitations

- **SQLite**: Single-writer. Gunicorn limited to 1 worker + N threads. For high traffic, consider PostgreSQL migration.
- **SAT sync via PHP subprocess**: Depends on `php` binary and `sat_sync/sync.php`. No native Python SAT client yet.
- **pdfplumber optional**: Bank PDF parsing requires `pdfplumber`; not installed by default.
- **No email delivery**: Forgot-password and verification email flows require external SMTP configuration (not included).
- **Single-node only**: No horizontal scaling. Backup restore is single-server.
