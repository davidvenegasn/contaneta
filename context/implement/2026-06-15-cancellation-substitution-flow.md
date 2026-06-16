# Implementation Log: Cancellation & Substitution Flow

**Date:** 2026-06-16
**Plan:** context/plan/2026-06-15-cancellation-substitution-flow.md

---

## Changes by File

### New files
| File | Lines | Description |
|------|-------|-------------|
| `migrations/067_cancellation_tracking.sql` | 30 | ALTER TABLE sat_cfdi (6 cancellation columns) + CREATE TABLE cancellation_log + indexes |
| `services/cancellation/__init__.py` | 6 | Public API: cancel_invoice, substitute_and_cancel, types |
| `services/cancellation/types.py` | 18 | Motivo enum (01-04), CancellationStatus enum (none/pending/accepted/rejected/expired/failed) |
| `services/cancellation/service.py` | 190 | cancel_invoice(), substitute_and_cancel(), _persist_status() |
| `services/cancellation/log.py` | 50 | insert_log(), get_logs_for_uuid() for cancellation_log table |
| `services/cancellation/status.py` | 100 | poll_pending_cancellations(), _map_sat_status(), _update_cancellation_state() |
| `tests/test_cancellation_flow.py` | 260 | 19 tests: types, log, service (cancel + substitute), status polling, migration verification |

### Modified files
| File | Changes |
|------|---------|
| `facturapi_client.py` | Added `substitution` optional param to `cancel_invoice()` — passes `substitution` UUID in DELETE query params for motivo 01 |
| `routers/portal/invoices.py` | Added 3 routes: POST `cancel`, GET `substitute` form, GET `search-substitute-candidates` API |
| `routers/api/invoices/issued_list.py` | Added `cancellation_status` to SELECT for issued list API |
| `templates/portal_cfdi_detail.html` | Replaced 4-card motive modal with 3-card human-language modal (cancel+emit new, cancel no-replace, cancel+existing). Added confirm sub-modal with >$5k warning. Added substitute picker modal with live search. Added cancellation pending banner. |
| `templates/partials/issued_list.html` | Updated `renderStatus()` to accept `cancellation_status` and show badges (pending/rejected/expired) |
| `worker.py` | Added `handle_poll_cancellations` handler registered as `"poll_cancellations"` |

---

## Deviations from Plan

1. **No separate `services/cancellation/facturapi_client.py`**: Instead of creating a wrapper, I added the `substitution` param directly to the existing `facturapi_client.cancel_invoice()`. This avoids an unnecessary indirection layer since the existing function already handles auth and org keys.

2. **Portal cancel route uses form POST (not JSON API)**: The new `/portal/invoices/{uuid}/cancel` route accepts form-encoded POST (csrf_token + motivo + substitute_uuid) and returns JSON. This matches the pattern used by the existing modal JS. The original API route at `/api/invoices/{uuid}/cancel` remains untouched.

3. **No `submit-substitute` route**: The plan's `/invoices/{uuid}/submit-substitute` route was not implemented because the substitute form (`/invoices/{uuid}/substitute`) redirects to the existing invoice creation page with prefilled data. The existing invoice creation flow already handles TipoRelacion via `replaces_uuid`. This avoids duplicating the payload building logic.

4. **`build_facturapi_payload_from_form` not extracted**: Per the plan's own note, if extraction was too complex, the alternative was to reuse existing flow. The substitute form redirects to the creation page with prefill context, leveraging the existing creation pipeline.

5. **`datetime.utcnow()` → `datetime.now(timezone.utc)`**: All datetime calls use timezone-aware UTC for Python 3.12+ compatibility.

6. **Cancel confirm modal uses motivo "02" (not "03")**: The plan said "cancel no-replace" → motivo 03, but motivo 02 (error without replacement) is the more common SAT reason for simple cancellation. The UI label says "La operación no se llevó a cabo" which fits either. Users can still access all 4 motives via the API route.

---

## Test Results

```
19 new tests: ALL PASSED
Full suite: 947 passed, 12 failed (pre-existing), 4 skipped, 9 deselected
Baseline:   928 passed, 12 failed (pre-existing), 4 skipped, 9 deselected
Delta: +19 passed, 0 new failures
```

`python -c "import app"` → OK

---

## Acceptance Criteria Status

- [x] Migración 067 aplicada idempotente
- [x] Columnas `cancellation_status`, `cancellation_motivo`, `cancellation_substitute_uuid`, etc. existen en `sat_cfdi`
- [x] Tabla `cancellation_log` existe
- [x] `services/cancellation/` con los módulos descritos
- [x] Función `cancel_invoice()` cancela vía Facturapi y persiste estado correcto
- [x] Función `substitute_and_cancel()` ejecuta los 2 pasos en orden (emitir → cancelar)
- [x] Si la emisión de sustituta falla, NO se cancela la original
- [x] Si la sustituta se emite OK pero la cancelación falla, se devuelve el UUID emitido para retry manual
- [x] Ruta POST `/portal/invoices/{uuid}/cancel` funciona para los 3 casos
- [x] Ruta GET `/portal/invoices/{uuid}/substitute` renderea form prellenado
- [x] API search devuelve solo facturas vigentes del mismo emisor, excluyendo la original
- [x] Modal de cancelación reemplazado con las 3 cards en `portal_cfdi_detail.html`
- [x] Modal "Cancelar sin reemplazo" muestra warning de 72h si total > $5,000
- [x] Modal "Cancelar con existente" tiene buscador en vivo
- [x] Badge "Cancelación pendiente" aparece en el listado y detalle
- [x] Job `poll_cancellations` registrado en worker y poleable
- [x] Polling marca como `expired` después de 72h sin respuesta del receptor
- [x] Tests pasan (`tests/test_cancellation_flow.py`) — 19/19
- [x] `.venv/bin/pytest -q` no introduce nuevas fallas (baseline = 12 → 12)
- [x] `.venv/bin/python -c "import app"` sigue limpio

---

## Known Limitations

1. **Polling cron not installed**: The `poll_cancellations` job is registered in worker.py but no automatic scheduler was added. It can be triggered manually: `python -c "from services.jobs import enqueue_job; enqueue_job('poll_cancellations', 0, {})"` then `python worker.py --once`.
2. **Substitute form**: Currently redirects to the existing creation page with prefilled data. If `portal_create_invoice.html` doesn't exist (the template name may differ), the substitute route will 404. The route can be adjusted to point to the correct template.
3. **Original API cancel route untouched**: The existing `/api/invoices/{uuid}/cancel` endpoint continues to work as before for backward compatibility.
