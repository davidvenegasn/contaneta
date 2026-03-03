# Release Prep Status — 2026-03-03

## Branch
`release-prep-20260303` (from `main` @ `eb02b91`)

## Backup
`backup/contaneta_pre_release_20260303_0236.zip` (2.2 MB)

## Git Status (snapshot)

### Modified (unstaged)
- `app.py`
- `docs/OPS_RUNBOOK.md`
- `routers/admin.py`
- `routers/api.py`
- `routers/invoicing.py`
- `routers/portal.py`
- `scripts/sat_worker.py`
- `services/bank_parse_preview.py`
- `services/invoices_engine.py`
- `static/css/components.css`
- `static/css/portal_components.css`
- `static/css/portal_shell.css`
- `static/css/portal_tokens.css`
- `static/css/portal_ui_v2.css`
- `templates/admin_issuer_detail.html`
- `templates/admin_job_detail.html`
- `templates/base_portal.html`
- `templates/components/portal_drawer.html`
- `templates/components/portal_rail.html`
- `templates/partials/bank_upload.html`
- `templates/portal_bank_pdf_to_excel.html`
- `worker.py`

### Untracked (new files)
- `docs/ADMIN_OPS_PLAN.md`
- `docs/ADMIN_RUNBOOK.md`
- `docs/SAT_AUTOSYNC_POLICY.md`
- `migrations/034_sat_sync_state_ops.sql`
- `scripts/sat_scheduler.py`
- `services/sat_autosync.py`
- `services/sat_job_handlers.py`
- `static/js/guides.js`
- `templates/portal_guides.html`

## Recent Commits (last 10)
```
eb02b91 feat: friendlier invoice form — rename sections, tooltips, retention hint
a2e4101 docs: deployment guide + .env.example with encryption/admin vars
6235d23 docs: operations runbook (logging, backups, admin, incidents)
576b483 security: tenant isolation audit + safe_update defense-in-depth
b15e3d8 ops: SAT worker logging + jobs/cron documentation
8e0cd5a docs: SAT credentials security documentation (FIEL encryption at rest)
af291d8 security: auth prod ready — session invalidation on password change
3bab4bb docs: launch audit + checklist + release smoke script
c88844d fix: topbar user dropdown z-index and overflow stacking
e20bcf3 perf: add query indices and in-memory catalog cache
```

## Today's Checklist

- [x] Backup ZIP created
- [x] Branch `release-prep-20260303` created
- [x] This status document created
- [ ] JOB 1: SAT AutoSync PRO — scheduler + policy + onboarding + dedupe
- [ ] JOB 3: Admin Ops PRO — dashboard + issuers + jobs + errors + actions
- [ ] JOB 4: Deploy VPS PRO — nginx + gunicorn + systemd + SSL + backups
- [ ] Final integration testing
- [ ] Merge to main
