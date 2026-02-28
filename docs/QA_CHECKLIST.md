# QA Checklist — Mega-Job 2026-02-27

## Pre-requisites
- [ ] Server starts without errors: `./run_server.sh`
- [ ] `pytest -q` passes (17 tests)
- [ ] Migrations auto-apply (029-031)

## JOB 1 — Month Close Dashboard
- [ ] Navigate to `/portal/month-close`
- [ ] Month selector (YYYY-MM) works
- [ ] Checklist items show with correct status (Listo/Pendiente)
- [ ] Override buttons toggle checklist items
- [ ] "Marcar como enviado" changes status to submitted
- [ ] "Confirmar cierre" changes status to confirmed
- [ ] "Reabrir" reverts to draft
- [ ] Upload acuse PDF works (only accepts PDF, max 10MB)
- [ ] Upload opinion PDF works
- [ ] Download acuse/opinion after upload
- [ ] API: `GET /api/month-close?ym=2026-02` returns correct data
- [ ] API: `POST /api/month-close` saves status + checklist

## JOB 2 — Matching Movements-CFDI
- [ ] Navigate to `/portal/movimientos`
- [ ] "Factura probable" column shows matched UUIDs with score badges
- [ ] Match filter: "Todos" shows all movements
- [ ] Match filter: "Sin match" filters correctly
- [ ] Match filter: "Match probable" filters score >= 80
- [ ] Match filter: "Revisar (50-79)" filters 50-79 range
- [ ] "Actualizar conciliacion" button refreshes suggestions
- [ ] API: `GET /api/matching/preview?ym=2026-02` returns summary

## JOB 3 — Bank Classification + Own Transfers
- [ ] Navigate to `/portal/bank/accounts` — CRUD works (add/edit/delete)
- [ ] In `/portal/movimientos`:
  - [ ] "Ocultar traspasos propios" checkbox works
  - [ ] "Ocultar pagos financieros" checkbox works
  - [ ] "Solo gastos reales" checkbox hides transfers + financial + commissions
- [ ] Pagination links preserve all filter params

## JOB 6 — Notifications Center
- [ ] Home (`/portal/home`) shows "Centro de accion" card
- [ ] Notifications display with color-coded severity borders
- [ ] Badge count shows unread notification count
- [ ] "Ir a resolver" buttons link correctly
- [ ] "Descartar" marks notification as read
- [ ] "Acciones sugeridas" section shows contextual actions
- [ ] API: `GET /api/notifications` returns notifications list
- [ ] API: `POST /api/notifications/{id}/read` marks as read

## JOB 4 — Invoice Engine
- [ ] Submit invoice via `/submit` works (uses invoices_engine)
- [ ] CFDI 4.0 receiver validation catches:
  - [ ] Invalid RFC format
  - [ ] Missing legal name
  - [ ] Invalid zip code (not 5 digits)
  - [ ] Missing tax system
- [ ] Payment complement (tipo=P) skips receiver validation
- [ ] Quick invoice from Home works

## JOB 7 — Plans + Limits + Paywall
- [ ] Navigate to `/portal/plan`
- [ ] Current plan shown with label and price
- [ ] Usage bars show correct counts (invoices, syncs, imports)
- [ ] All 4 plans displayed in card grid (Free, Trial, Basic, Pro)
- [ ] Current plan highlighted with border
- [ ] "Elegir" button triggers Stripe checkout
- [ ] Plan limits enforce correctly (check_limit returns allowed=false when over limit)

## General
- [ ] No console errors on any page
- [ ] CSRF tokens work on all POST forms
- [ ] Multi-tenant isolation maintained (all queries filter by issuer_id)
- [ ] No secrets exposed in templates or API responses
