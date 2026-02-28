# Resume Status — 2026-02-27 (post mega-job)

## Git Log (ultimos commits)

```
66b692f feat: plans + limits + paywall
5dd4f5f refactor: unify invoice engine
fb9e01d feat: notifications center
5e0766f feat: bank classification + own transfers
beecd06 feat: matching movements-cfdi
c0c1d2e feat: month close dashboard
d21b0d6 ops: secure FIEL handling in SAT sync scripts and improved backup/smoke tests
c5cecf1 feat: robust jobs, crypto at-rest, notifications, month close, and matching improvements
```

## Feature Status

### COMPLETO (Mega-Job)

| Feature | Archivos clave | Como probar |
|---------|---------------|-------------|
| **Month Close Dashboard** | migrations/029, services/month_close.py, routers/api.py, routers/portal.py, templates/portal_month_close.html | `/portal/month-close` — selector mes, checklist, status transitions (draft/submitted/confirmed), upload acuse/opinion |
| **Matching Preview** | services/matching.py (preview_month), routers/api.py | `GET /api/matching/preview?ym=YYYY-MM` — summary of matches by quality |
| **Matching UI** | templates/portal_bank_movements.html, routers/portal.py | `/portal/movimientos` — filtro chips: Sin match / Probable / Revisar (50-79) |
| **Bank Classification** | services/bank_classification.py | Auto-clasifica: CUENTA_PROPIA (CLABE match), FINANCIERO_PAGO_TARJETA, COMISION_BANCARIA, NOMINA |
| **Own Transfers Toggle** | templates/portal_bank_movements.html, routers/portal.py | Toggle "Solo gastos reales" oculta traspasos + financieros + comisiones |
| **Notifications Center** | migrations/030, services/notifications.py, templates/portal_home.html | `/portal/home` — Centro de accion con severity borders, badge count, acciones sugeridas |
| **Notifications API** | routers/api.py | `GET /api/notifications`, `POST /api/notifications/{id}/read` |
| **Invoice Engine** | services/invoices_engine.py, routers/invoicing.py | Validacion CFDI 4.0 (RFC, CP, regimen), compute taxes, unified builder. Submit via `/submit` |
| **Plans + Limits** | migrations/031, services/plans.py, services/plan_guard.py | 4 planes (FREE/TRIAL/BASIC/PRO) con limites por mes |
| **Plan Page** | templates/portal_plan.html, routers/portal.py | `/portal/plan` — usage bars, plan grid, upgrade buttons |

### PRE-EXISTENTE (antes del mega-job)

| Feature | Estado |
|---------|--------|
| Jobs Queue (service) | Completo |
| Admin: Jobs Dashboard | Completo |
| Admin: Error Events | Completo |
| Bank Accounts CRUD | Completo |
| Crypto at Rest | Completo |
| SAT Credentials Secure | Completo |
| Billing (Stripe) | Completo |
| Migrations 025-028 | Completo |

### INCOMPLETO / PENDIENTE

| Feature | Estado | Que falta |
|---------|--------|-----------|
| **Admin: Issuer Meta** | ROTO | Syntax error en `admin_issuer.py:62` (falta `)`) — template `admin_issuer_detail.html` no existe |
| **Worker: Job Handlers** | STUB | `_load_handlers()` retorna dict vacio — jobs se encolan pero ninguno se procesa |
| **Plan enforcement** | PARCIAL | `check_limit()` existe pero no se llama en todas las rutas. Falta integrar en: submit invoice, SAT sync, bank import |

## Migraciones

| # | Archivo | Que hace |
|---|---------|----------|
| 029 | month_close_enhance.sql | status enum, checklist_json, pdf paths en month_close_status |
| 030 | notifications_meta.sql | meta_json column en notifications |
| 031 | plans.sql | plan + limits en issuers, plan_usage table |

## Tests

- 17 tests passing (`pytest -q`)
- QA checklist: `docs/QA_CHECKLIST.md`

## Nuevos Archivos

| Archivo | Proposito |
|---------|-----------|
| migrations/029_month_close_enhance.sql | Enhance month close schema |
| migrations/030_notifications_meta.sql | Add meta_json to notifications |
| migrations/031_plans.sql | Plans + usage tracking |
| services/bank_classification.py | Auto-classification rules |
| services/plans.py | Plan definitions + limits + usage |
| services/plan_guard.py | Limit checking dependency |
| docs/QA_CHECKLIST.md | Manual QA checklist |
