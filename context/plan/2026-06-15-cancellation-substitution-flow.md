# Job: Cancelación de CFDI + Sustitución (TipoRelacion 04) end-to-end

**Fecha:** 2026-06-15
**Owner:** David
**Tipo:** Feature (CFDI 4.0 — cancelación real contra SAT/Facturapi)
**Duración estimada:** 1.5–2 días autónomos
**Modo:** Autónomo — ejecutar de corrido. Si encuentras un bloqueador, documéntalo en el log y sigue con el siguiente paso.

---

## Contexto

Hoy el modal de cancelación existe (4 motivos con cards) pero **no ejecuta la cancelación real contra Facturapi/SAT**. El usuario ve la UI pero la factura no se cancela. Además, **falta el flujo de sustitución (TipoRelacion 04)** que el SAT exige para el motivo 01.

La nueva UX simplifica el modal actual a **3 opciones grandes con lenguaje humano** (no códigos de motivo):

```
┌──────────────────────────────────────────────────────┐
│ ¿Qué quieres hacer con esta factura?                  │
│                                                       │
│  🔄  Cancelar y emitir una nueva                      │
│      Para corregir errores. Motivo 01.                │
│                                                       │
│  🚫  Cancelar sin reemplazo                           │
│      La operación no se llevó a cabo.                 │
│                                                       │
│  📋  Cancelar y sustituir con otra ya emitida         │
│      Ya tengo el reemplazo timbrado.                  │
└──────────────────────────────────────────────────────┘
```

Y la opción "Cancelar y emitir una nueva" debe abrir el form de creación **prellenado con los datos de la original** para que el usuario solo edite lo que tiene que cambiar.

## Regla técnica crítica del SAT

Para motivo 01 (con sustitución), el SAT exige que **la nueva factura exista PRIMERO**. El orden es:

1. Emitir nueva CFDI con `CfdiRelacionados.TipoRelacion = "04"` apuntando al UUID original.
2. Cancelar la original con motivo 01 + folio_sustitucion = UUID de la nueva.

Si se invierte el orden, SAT rechaza la cancelación.

## Regla técnica del receptor

CFDIs con monto > $5,000 MXN requieren aceptación del receptor (vía Buzón Tributario, 72 horas). Estados posibles del proceso de cancelación:

- `none` — no se ha cancelado
- `pending` — cancelación enviada, esperando aceptación del receptor
- `accepted` — receptor aceptó o no requería aceptación
- `rejected` — receptor rechazó (la factura sigue vigente)
- `expired` — pasaron 72h sin respuesta (SAT asume aceptación)

## Restricciones

- **No hacer breaking changes** en rutas existentes
- **Migración idempotente**
- **Tests verdes antes y después**: baseline 12 fallas pre-existentes (`test_facturapi_provision`, `test_fiscal_route`, `test_portal_manifesto`, `test_sat_cron_tiers`)
- **No tocar el flujo de timbrado normal** — solo agregar el caso especial de "emitir como sustitución"
- **Lenguaje en código: inglés. UI: español MX.**
- **El modal actual de 4 motivos** (en `templates/portal_cfdi_detail.html`) se reemplaza completo con el nuevo flujo de 3 cards

---

## Plan de implementación (en orden)

### Paso 1 — Migración 067

Archivo: `migrations/067_cancellation_tracking.sql`

```sql
-- Migration 067: cancellation status tracking for CFDI

ALTER TABLE sat_cfdi ADD COLUMN cancellation_status TEXT;       -- none, pending, accepted, rejected, expired
ALTER TABLE sat_cfdi ADD COLUMN cancellation_motivo TEXT;       -- 01, 02, 03, 04
ALTER TABLE sat_cfdi ADD COLUMN cancellation_substitute_uuid TEXT;
ALTER TABLE sat_cfdi ADD COLUMN cancellation_requested_at TEXT;
ALTER TABLE sat_cfdi ADD COLUMN cancellation_finalized_at TEXT;
ALTER TABLE sat_cfdi ADD COLUMN cancellation_requested_by_user_id INTEGER;

CREATE INDEX IF NOT EXISTS idx_sat_cfdi_cancel_status
  ON sat_cfdi(cancellation_status)
  WHERE cancellation_status IS NOT NULL;

-- Audit log specifically for cancellations
CREATE TABLE IF NOT EXISTS cancellation_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  cfdi_uuid TEXT NOT NULL,
  motivo TEXT NOT NULL,                  -- 01/02/03/04
  substitute_uuid TEXT,                  -- only for motivo 01
  event TEXT NOT NULL,                   -- requested, accepted, rejected, expired, failed
  provider_response_json TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cancellation_log_issuer
  ON cancellation_log(issuer_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cancellation_log_uuid
  ON cancellation_log(cfdi_uuid);
```

### Paso 2 — Servicio de cancelación

Crear `services/cancellation/` con:

```
services/cancellation/
├── __init__.py
├── service.py        # main API: cancel_invoice(), substitute_and_cancel()
├── facturapi_client.py  # wrapper de Facturapi cancellation API
├── status.py         # polling de status, transición de estados
├── log.py            # cancellation_log CRUD
└── types.py          # enums (Motivo, CancellationStatus)
```

**`services/cancellation/types.py`**:

```python
"""Types for cancellation flow."""
from enum import Enum


class Motivo(str, Enum):
    ERROR_CON_RELACION = "01"      # Con sustitución
    ERROR_SIN_RELACION = "02"      # Sin sustitución
    NO_OPERACION = "03"             # Operación no realizada
    GLOBAL = "04"                   # Operación nominativa relacionada en global


class CancellationStatus(str, Enum):
    NONE = "none"
    PENDING = "pending"             # Enviada a SAT, esperando receptor
    ACCEPTED = "accepted"           # Receptor aceptó o no requirió
    REJECTED = "rejected"           # Receptor rechazó
    EXPIRED = "expired"             # 72h sin respuesta → SAT asume aceptación
    FAILED = "failed"               # Error técnico al cancelar
```

**`services/cancellation/service.py`** — API pública:

```python
"""Public API for CFDI cancellation flow."""
import logging
from typing import Optional

from database import db
from services.cancellation.facturapi_client import (
    cancel_via_facturapi,
    FacturapiCancellationError,
)
from services.cancellation.log import insert_log
from services.cancellation.types import Motivo, CancellationStatus

logger = logging.getLogger(__name__)


def cancel_invoice(
    *,
    issuer_id: int,
    user_id: int,
    cfdi_uuid: str,
    motivo: Motivo,
    substitute_uuid: Optional[str] = None,
) -> dict:
    """Cancel a CFDI against SAT via Facturapi.

    For motivo "01", substitute_uuid is REQUIRED and must already be a timbered
    CFDI. The caller is responsible for emitting the substitute BEFORE calling
    this function.

    Returns dict with keys:
      - status: CancellationStatus value
      - sat_status: raw status from Facturapi response
      - requires_receptor_acceptance: bool

    Raises ValueError for invalid input, FacturapiCancellationError for SAT errors.
    """
    if motivo == Motivo.ERROR_CON_RELACION and not substitute_uuid:
        raise ValueError("Motivo 01 requiere folio de sustitución (substitute_uuid).")

    conn = db()
    inv = conn.execute(
        """SELECT id, uuid, total, facturapi_invoice_id, customer_rfc, facturapi_org_id
             FROM invoices
            WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) LIMIT 1""",
        (issuer_id, cfdi_uuid.strip()),
    ).fetchone()
    if not inv:
        conn.close()
        raise ValueError(f"CFDI {cfdi_uuid} no encontrado para emisor {issuer_id}.")
    inv = dict(inv)
    conn.close()

    insert_log(
        issuer_id=issuer_id, user_id=user_id, cfdi_uuid=cfdi_uuid,
        motivo=motivo.value, substitute_uuid=substitute_uuid, event="requested",
    )

    try:
        provider_resp = cancel_via_facturapi(
            org_id=inv["facturapi_org_id"],
            invoice_id=inv["facturapi_invoice_id"],
            motive=motivo.value,
            substitution=substitute_uuid,
        )
    except FacturapiCancellationError as exc:
        insert_log(
            issuer_id=issuer_id, user_id=user_id, cfdi_uuid=cfdi_uuid,
            motivo=motivo.value, event="failed", error_message=str(exc),
        )
        raise

    # Determine local status from provider response
    sat_status = provider_resp.get("status", "").lower()
    requires_acceptance = float(inv["total"] or 0) > 5000.0

    if sat_status in ("canceled", "cancelled"):
        new_status = CancellationStatus.ACCEPTED
    elif sat_status in ("pending", "in_process"):
        new_status = CancellationStatus.PENDING
    else:
        new_status = CancellationStatus.PENDING if requires_acceptance else CancellationStatus.ACCEPTED

    _persist_status(
        issuer_id=issuer_id,
        cfdi_uuid=cfdi_uuid,
        motivo=motivo.value,
        substitute_uuid=substitute_uuid,
        status=new_status,
        user_id=user_id,
    )

    if new_status == CancellationStatus.ACCEPTED:
        insert_log(
            issuer_id=issuer_id, user_id=user_id, cfdi_uuid=cfdi_uuid,
            motivo=motivo.value, event="accepted",
            provider_response_json=str(provider_resp),
        )

    return {
        "status": new_status.value,
        "sat_status": sat_status,
        "requires_receptor_acceptance": requires_acceptance,
    }


def substitute_and_cancel(
    *,
    issuer_id: int,
    user_id: int,
    original_uuid: str,
    new_cfdi_payload: dict,
) -> dict:
    """Two-step flow for motivo 01:
       1. Emit new CFDI with CfdiRelacionados TipoRelacion=04 → original_uuid
       2. Cancel original with motivo 01 → new UUID

    The caller (route handler) MUST inject `related_documents` into
    new_cfdi_payload with {"relationship": "04", "documents": [{"uuid": original_uuid}]}.

    Returns dict with keys:
      - substitute_uuid: UUID of the newly timbered CFDI
      - cancellation_status: status of the original after cancellation
      - sat_status: raw response
    """
    from facturapi_client import create_invoice, FacturapiError

    conn = db()
    orig = conn.execute(
        """SELECT facturapi_org_id FROM invoices
            WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) LIMIT 1""",
        (issuer_id, original_uuid.strip()),
    ).fetchone()
    conn.close()
    if not orig:
        raise ValueError(f"Original {original_uuid} no encontrada.")
    org_id = dict(orig)["facturapi_org_id"]

    # Ensure substitution relationship is present
    rel = new_cfdi_payload.get("related_documents") or []
    has_sub = any(r.get("relationship") == "04" for r in rel)
    if not has_sub:
        new_cfdi_payload["related_documents"] = rel + [{
            "relationship": "04",
            "documents": [{"uuid": original_uuid}],
        }]

    # Step 1: emit substitute
    try:
        new_invoice = create_invoice(issuer_id, org_id, new_cfdi_payload)
    except FacturapiError as exc:
        logger.exception("substitute emission failed for original=%s", original_uuid)
        raise

    substitute_uuid = (new_invoice.get("uuid") or "").lower()
    if not substitute_uuid:
        raise RuntimeError("Facturapi no devolvió UUID para la sustitución.")

    # Step 2: cancel original referencing the new one
    try:
        cancel_result = cancel_invoice(
            issuer_id=issuer_id,
            user_id=user_id,
            cfdi_uuid=original_uuid,
            motivo=Motivo.ERROR_CON_RELACION,
            substitute_uuid=substitute_uuid,
        )
    except Exception as exc:
        # Substitute is timbered but cancellation failed — surface the issue
        # so the user can retry cancel manually (substitute is preserved).
        logger.exception(
            "Substitute timbered (uuid=%s) but cancel of original failed", substitute_uuid
        )
        return {
            "substitute_uuid": substitute_uuid,
            "cancellation_status": "failed",
            "error": str(exc),
        }

    return {
        "substitute_uuid": substitute_uuid,
        "cancellation_status": cancel_result["status"],
        "sat_status": cancel_result["sat_status"],
        "requires_receptor_acceptance": cancel_result["requires_receptor_acceptance"],
    }


def _persist_status(
    *,
    issuer_id: int,
    cfdi_uuid: str,
    motivo: str,
    substitute_uuid: Optional[str],
    status: CancellationStatus,
    user_id: int,
) -> None:
    from datetime import datetime
    now = datetime.utcnow().isoformat()
    final_ts = now if status == CancellationStatus.ACCEPTED else None
    conn = db()
    conn.execute(
        """UPDATE sat_cfdi
              SET cancellation_status = ?,
                  cancellation_motivo = ?,
                  cancellation_substitute_uuid = ?,
                  cancellation_requested_at = COALESCE(cancellation_requested_at, ?),
                  cancellation_finalized_at = COALESCE(cancellation_finalized_at, ?),
                  cancellation_requested_by_user_id = COALESCE(cancellation_requested_by_user_id, ?),
                  updated_at = ?
            WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?)""",
        (status.value, motivo, substitute_uuid, now, final_ts, user_id, now, issuer_id, cfdi_uuid),
    )
    # Also update local invoices table if applicable
    conn.execute(
        """UPDATE invoices SET status = ?
            WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?)""",
        ("cancelled" if status == CancellationStatus.ACCEPTED else "pending_cancel",
         issuer_id, cfdi_uuid),
    )
    conn.commit()
    conn.close()
```

**`services/cancellation/facturapi_client.py`** — wrapper de la API Facturapi de cancelación:

```python
"""Wrapper for Facturapi cancellation endpoint."""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class FacturapiCancellationError(Exception):
    pass


def cancel_via_facturapi(
    *,
    org_id: str,
    invoice_id: str,
    motive: str,
    substitution: Optional[str] = None,
) -> dict:
    """Call Facturapi DELETE /invoices/:id?motive=01&substitution=UUID."""
    from facturapi_client import _facturapi_request  # reusar helper existente
    params = {"motive": motive}
    if substitution:
        params["substitution"] = substitution
    try:
        resp = _facturapi_request(
            method="DELETE",
            org_id=org_id,
            path=f"/v2/invoices/{invoice_id}",
            params=params,
        )
    except Exception as exc:
        raise FacturapiCancellationError(str(exc))
    return resp
```

> **Nota:** Verificar el helper real que tiene `facturapi_client.py` y adaptarlo. Si no hay un `_facturapi_request` genérico, escribir uno o llamar directo a Facturapi vía httpx.

### Paso 3 — Rutas de cancelación

En `routers/portal/invoices.py` añadir:

```python
@router.post("/invoices/{uuid}/cancel", response_class=HTMLResponse)
async def portal_cancel_invoice(
    request: Request,
    uuid: str,
    issuer: dict = Depends(get_portal_issuer),
):
    """Cancel an existing CFDI. Body params:
       - csrf_token
       - motivo: 01, 02, 03, 04
       - substitute_uuid (only when motivo=01 and option=existing)
    """
    from services.cancellation.service import cancel_invoice
    from services.cancellation.types import Motivo
    form = await request.form()
    if not csrf_service.verify_csrf_token(form.get("csrf_token", "")):
        raise HTTPException(status_code=403, detail="CSRF inválido")

    motivo_raw = (form.get("motivo") or "").strip()
    substitute_uuid = (form.get("substitute_uuid") or "").strip() or None
    try:
        motivo = Motivo(motivo_raw)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Motivo inválido: {motivo_raw}")

    try:
        result = cancel_invoice(
            issuer_id=issuer["id"],
            user_id=request.state.user_id,
            cfdi_uuid=uuid,
            motivo=motivo,
            substitute_uuid=substitute_uuid,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Cancel failed")
        raise HTTPException(status_code=502, detail=f"Error al cancelar: {exc}")

    return JSONResponse({"ok": True, **result})


@router.get("/invoices/{uuid}/substitute", response_class=HTMLResponse)
def portal_substitute_form(
    request: Request, uuid: str, issuer: dict = Depends(get_portal_issuer),
):
    """Render the invoice creation form prefilled with the ORIGINAL invoice data,
    so the user can edit and emit a substitute. On submit, the substitute_and_cancel
    flow runs in the POST handler /invoices/{uuid}/submit-substitute.
    """
    issuer_id = issuer["id"]
    conn = db()
    inv = conn.execute(
        """SELECT * FROM invoices WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) LIMIT 1""",
        (issuer_id, uuid.strip()),
    ).fetchone()
    if not inv:
        conn.close()
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    inv = dict(inv)
    items_rows = conn.execute(
        "SELECT * FROM invoice_items WHERE invoice_id = ? ORDER BY id", (inv["id"],),
    ).fetchall()
    conn.close()

    # Render the existing creation form but with prefill_from_original context
    return _render_portal(
        request, issuer=issuer,
        template_name="form.html",  # the existing creation form
        active_page="create",
        title="Emitir reemplazo",
        extra={
            "csrf_token": csrf_service.generate_csrf_token(),
            "substitute_for_uuid": inv["uuid"],
            "customer_prefill": {
                "customer_rfc": inv["customer_rfc"],
                "customer_legal_name": inv["customer_legal_name"],
                "customer_zip": inv["customer_zip"],
                "customer_tax_system": inv["customer_tax_system"],
                "customer_email": inv.get("customer_email"),
            },
            "items_prefill": [dict(r) for r in items_rows],
            "comprobante_prefill": {
                "tipo_comprobante": inv["tipo_comprobante"],
                "currency": inv["currency"],
                "payment_method": inv["payment_method"],
                "payment_form": inv["payment_form"],
                "cfdi_use": inv["cfdi_use"],
            },
        },
    )


@router.post("/invoices/{uuid}/submit-substitute", response_class=HTMLResponse)
async def portal_submit_substitute(
    request: Request, uuid: str, issuer: dict = Depends(get_portal_issuer),
):
    """Two-step flow: emit substitute + cancel original. Calls substitute_and_cancel()."""
    from services.cancellation.service import substitute_and_cancel
    from services.invoices.invoices_engine import build_facturapi_payload_from_form

    form = await request.form()
    if not csrf_service.verify_csrf_token(form.get("csrf_token", "")):
        raise HTTPException(status_code=403, detail="CSRF inválido")

    # Build the new CFDI payload using the SAME logic as normal creation
    payload = build_facturapi_payload_from_form(form, issuer)
    # Inject TipoRelacion 04 → original UUID
    payload["related_documents"] = [
        {"relationship": "04", "documents": [{"uuid": uuid}]}
    ]

    try:
        result = substitute_and_cancel(
            issuer_id=issuer["id"],
            user_id=request.state.user_id,
            original_uuid=uuid,
            new_cfdi_payload=payload,
        )
    except Exception as exc:
        logger.exception("Substitute+cancel failed")
        raise HTTPException(status_code=502, detail=str(exc))

    # Redirect to the new CFDI detail
    return RedirectResponse(
        url=f"/portal/cfdi/issued/{result['substitute_uuid']}?substituted=1",
        status_code=303,
    )
```

> Si `build_facturapi_payload_from_form` no existe en `services/invoices/invoices_engine.py`, **extraer** la lógica desde `routers/invoicing.py:_submit_impl` en una función reusable. Esto refactor es necesario porque sustitución y creación normal deben compartir 100% la construcción del payload.

### Paso 4 — Reemplazar el modal de cancelación

Modificar `templates/portal_cfdi_detail.html`. El modal actual (4 cards de motivos abstractos) se reemplaza por el nuevo de 3 cards con lenguaje humano:

```html
<div id="cancelModal" class="cancel-modal" hidden>
  <div class="cancel-modal__backdrop" data-close="1"></div>
  <div class="cancel-modal__panel" role="dialog" aria-modal="true">
    <button type="button" class="cancel-modal__close" data-close="1" aria-label="Cerrar">×</button>
    <h2 class="cancel-modal__title">¿Qué quieres hacer con esta factura?</h2>
    <p class="cancel-modal__subtitle">
      Folio {{ cfdi.serie|default('') }}{{ cfdi.folio|default('—') }} · ${{ "{:,.2f}".format(cfdi.total) }} {{ cfdi.moneda|default('MXN') }}
    </p>

    <div class="cancel-options">
      <a href="/portal/invoices/{{ cfdi.uuid }}/substitute" class="cancel-option">
        <div class="cancel-option__icon">🔄</div>
        <div class="cancel-option__body">
          <div class="cancel-option__title">Cancelar y emitir una nueva</div>
          <div class="cancel-option__hint">Para corregir errores. Motivo 01.</div>
        </div>
      </a>

      <button type="button" class="cancel-option" data-action="cancel-no-replace">
        <div class="cancel-option__icon">🚫</div>
        <div class="cancel-option__body">
          <div class="cancel-option__title">Cancelar sin reemplazo</div>
          <div class="cancel-option__hint">La operación no se llevó a cabo.</div>
        </div>
      </button>

      <button type="button" class="cancel-option" data-action="cancel-existing-replace">
        <div class="cancel-option__icon">📋</div>
        <div class="cancel-option__body">
          <div class="cancel-option__title">Cancelar y sustituir con otra ya emitida</div>
          <div class="cancel-option__hint">Ya tengo el reemplazo timbrado.</div>
        </div>
      </button>
    </div>
  </div>
</div>

<!-- Confirmation sub-modal for cancel-no-replace -->
<div id="cancelConfirmModal" class="cancel-modal" hidden>
  <div class="cancel-modal__backdrop" data-close="1"></div>
  <div class="cancel-modal__panel" role="dialog" aria-modal="true">
    <h2 class="cancel-modal__title">¿Seguro que quieres cancelar sin reemplazo?</h2>
    <p class="cancel-modal__subtitle">Esto cancela la factura definitivamente. No hay vuelta atrás.</p>
    {% if cfdi.total|float > 5000 %}
      <p class="cancel-modal__warn">⚠ Esta factura supera $5,000 MXN. El receptor tiene 72h para aceptar o rechazar la cancelación.</p>
    {% endif %}
    <div class="cancel-modal__actions">
      <button type="button" class="btn btn--ghost" data-close="1">Volver</button>
      <button type="button" class="btn btn--danger" id="cancelConfirmBtn">Sí, cancelar</button>
    </div>
  </div>
</div>

<!-- Picker for cancel-existing-replace (reuses NC picker structure) -->
<div id="substitutePickerModal" class="cancel-modal" hidden>
  <div class="cancel-modal__backdrop" data-close="1"></div>
  <div class="cancel-modal__panel cancel-modal__panel--large" role="dialog" aria-modal="true">
    <h2 class="cancel-modal__title">Elige la factura que sustituye a esta</h2>
    <p class="cancel-modal__subtitle">Solo se muestran tus facturas tipo Ingreso vigentes.</p>
    <input type="search" id="substituteSearch" placeholder="Buscar por UUID, RFC o nombre…" />
    <div id="substituteList" class="substitute-list">
      <!-- Lista cargada vía API -->
    </div>
    <div class="cancel-modal__actions">
      <button type="button" class="btn btn--ghost" data-close="1">Cerrar</button>
    </div>
  </div>
</div>
```

**JS** que conecta las 3 opciones:

```javascript
(function() {
  var modal = document.getElementById('cancelModal');
  var confirmModal = document.getElementById('cancelConfirmModal');
  var pickerModal = document.getElementById('substitutePickerModal');
  var cfdiUuid = '{{ cfdi.uuid }}';
  var csrf = '{{ csrf_token }}';

  function open(m) { m.hidden = false; }
  function close(m) { m.hidden = true; }

  // Open main modal
  document.querySelectorAll('[data-action="open-cancel"]').forEach(function(btn) {
    btn.addEventListener('click', function() { open(modal); });
  });

  // Close handlers
  document.querySelectorAll('[data-close="1"]').forEach(function(el) {
    el.addEventListener('click', function() {
      [modal, confirmModal, pickerModal].forEach(close);
    });
  });

  // Option 2: cancel without replacement
  modal.querySelector('[data-action="cancel-no-replace"]').addEventListener('click', function() {
    close(modal);
    open(confirmModal);
  });

  // Confirm cancel no-replace
  document.getElementById('cancelConfirmBtn').addEventListener('click', function() {
    var btn = this;
    btn.disabled = true; btn.textContent = 'Cancelando…';
    fetch('/portal/invoices/' + cfdiUuid + '/cancel', {
      method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: 'csrf_token=' + encodeURIComponent(csrf) + '&motivo=03',
    }).then(function(r) { return r.json(); }).then(function(j) {
      if (j.ok) {
        if (j.status === 'pending') {
          window.portalToast && window.portalToast({
            variant: 'info',
            title: 'Cancelación enviada',
            message: 'El receptor tiene 72h para aceptar la cancelación.',
          });
        } else {
          window.portalToast && window.portalToast({
            variant: 'success',
            title: 'Factura cancelada',
          });
        }
        setTimeout(function() { window.location.reload(); }, 1500);
      } else {
        alert('Error: ' + (j.detail || 'no se pudo cancelar'));
        btn.disabled = false; btn.textContent = 'Sí, cancelar';
      }
    });
  });

  // Option 3: cancel with existing substitute (open picker)
  modal.querySelector('[data-action="cancel-existing-replace"]').addEventListener('click', function() {
    close(modal);
    open(pickerModal);
    loadSubstituteCandidates('');
  });

  // Load substitute candidates from API
  function loadSubstituteCandidates(q) {
    fetch('/portal/api/invoices/search-issued-substitute-candidates?q=' + encodeURIComponent(q) + '&exclude=' + cfdiUuid)
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var list = document.getElementById('substituteList');
        list.innerHTML = '';
        (data.items || []).forEach(function(inv) {
          var row = document.createElement('button');
          row.type = 'button';
          row.className = 'substitute-row';
          row.innerHTML = '<div><strong>' + escapeHtml(inv.serie || '') + escapeHtml(inv.folio || '—') + '</strong> · ' + escapeHtml(inv.fecha_emision || '').slice(0,10) +
                          '</div><div class="substitute-row__client">' + escapeHtml(inv.nombre_receptor || '') + ' · ' + escapeHtml(inv.uuid) + '</div>' +
                          '<div class="substitute-row__total">$' + Number(inv.total || 0).toFixed(2) + '</div>';
          row.addEventListener('click', function() { confirmSubstitute(inv.uuid); });
          list.appendChild(row);
        });
        if ((data.items || []).length === 0) {
          list.innerHTML = '<p class="muted">No hay facturas que coincidan.</p>';
        }
      });
  }

  document.getElementById('substituteSearch').addEventListener('input', function(e) {
    loadSubstituteCandidates(e.target.value);
  });

  function confirmSubstitute(substituteUuid) {
    if (!confirm('Esto cancela la factura actual y la sustituye con ' + substituteUuid.slice(0,8) + '… ¿Continuar?')) return;
    fetch('/portal/invoices/' + cfdiUuid + '/cancel', {
      method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: 'csrf_token=' + encodeURIComponent(csrf) + '&motivo=01&substitute_uuid=' + encodeURIComponent(substituteUuid),
    }).then(function(r) { return r.json(); }).then(function(j) {
      if (j.ok) {
        window.location.reload();
      } else {
        alert('Error: ' + (j.detail || 'falló'));
      }
    });
  }

  function escapeHtml(s) {
    return String(s || '').replace(/[&<>"']/g, function(c) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }
})();
```

### Paso 5 — API search para candidatos de sustitución

En `routers/portal/invoices.py`:

```python
@router.get("/api/invoices/search-issued-substitute-candidates")
def search_substitute_candidates(
    request: Request,
    q: str = "",
    exclude: str = "",
    issuer: dict = Depends(get_portal_issuer),
):
    issuer_id = issuer["id"]
    conn = db()
    rows = conn.execute(
        """SELECT uuid, serie, folio, fecha_emision, rfc_receptor, nombre_receptor, total, moneda
             FROM sat_cfdi
            WHERE issuer_id = ?
              AND direction = 'issued'
              AND UPPER(COALESCE(tipo_comprobante,'')) = 'I'
              AND COALESCE(status,'') NOT IN ('0','C','cancelled','Cancelado')
              AND COALESCE(cancellation_status,'none') = 'none'
              AND LOWER(uuid) != LOWER(?)
              AND (
                ? = ''
                OR LOWER(uuid) LIKE '%' || LOWER(?) || '%'
                OR LOWER(rfc_receptor) LIKE '%' || LOWER(?) || '%'
                OR LOWER(nombre_receptor) LIKE '%' || LOWER(?) || '%'
              )
            ORDER BY fecha_emision DESC
            LIMIT 50""",
        (issuer_id, exclude, q, q, q, q),
    ).fetchall()
    conn.close()
    return {"items": [dict(r) for r in rows]}
```

### Paso 6 — Status polling job

Crear `services/cancellation/status.py`:

```python
"""Poll SAT/Facturapi for cancellation status updates."""
import logging
from datetime import datetime, timedelta

from database import db
from services.cancellation.facturapi_client import _facturapi_request
from services.cancellation.log import insert_log
from services.cancellation.types import CancellationStatus

logger = logging.getLogger(__name__)


def poll_pending_cancellations(limit: int = 100) -> dict:
    """Iterate all CFDI with cancellation_status='pending' and check SAT status.

    Should be invoked from a cron job (every 1 hour is reasonable).
    Returns counts of how many were updated.
    """
    conn = db()
    rows = conn.execute(
        """SELECT s.id, s.issuer_id, s.uuid, s.cancellation_requested_at,
                  i.facturapi_invoice_id, i.facturapi_org_id,
                  i.cancellation_requested_by_user_id
             FROM sat_cfdi s
             JOIN invoices i ON i.uuid = s.uuid AND i.issuer_id = s.issuer_id
            WHERE s.cancellation_status = 'pending'
            LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()

    stats = {"checked": 0, "accepted": 0, "rejected": 0, "expired": 0, "still_pending": 0}
    for r in rows:
        r = dict(r)
        stats["checked"] += 1
        try:
            resp = _facturapi_request(
                method="GET",
                org_id=r["facturapi_org_id"],
                path=f"/v2/invoices/{r['facturapi_invoice_id']}",
            )
        except Exception as exc:
            logger.warning("poll failed uuid=%s: %s", r["uuid"], exc)
            continue
        sat_status = (resp.get("status") or "").lower()
        new_status = _map_sat_status(sat_status, r["cancellation_requested_at"])
        if new_status == CancellationStatus.PENDING:
            stats["still_pending"] += 1
            continue
        _update_cancellation_state(r["issuer_id"], r["uuid"], new_status)
        insert_log(
            issuer_id=r["issuer_id"],
            user_id=r["cancellation_requested_by_user_id"] or 0,
            cfdi_uuid=r["uuid"],
            motivo="",
            event=new_status.value,
            provider_response_json=str(resp),
        )
        stats[new_status.value] = stats.get(new_status.value, 0) + 1
    return stats


def _map_sat_status(sat_status: str, requested_at: str) -> CancellationStatus:
    if sat_status in ("canceled", "cancelled"):
        return CancellationStatus.ACCEPTED
    if sat_status == "rejected":
        return CancellationStatus.REJECTED
    # If >72h since request, SAT auto-accepts (expired)
    try:
        req = datetime.fromisoformat(requested_at)
        if (datetime.utcnow() - req) > timedelta(hours=72):
            return CancellationStatus.EXPIRED
    except Exception:
        pass
    return CancellationStatus.PENDING


def _update_cancellation_state(issuer_id, uuid, status):
    now = datetime.utcnow().isoformat()
    conn = db()
    conn.execute(
        """UPDATE sat_cfdi
              SET cancellation_status = ?,
                  cancellation_finalized_at = ?,
                  updated_at = ?
            WHERE issuer_id = ? AND LOWER(uuid) = LOWER(?)""",
        (status.value, now, now, issuer_id, uuid),
    )
    final_local_status = "cancelled" if status in (CancellationStatus.ACCEPTED, CancellationStatus.EXPIRED) else "active"
    conn.execute(
        """UPDATE invoices SET status = ?
            WHERE issuer_id = ? AND LOWER(uuid) = LOWER(?)""",
        (final_local_status, issuer_id, uuid),
    )
    conn.commit()
    conn.close()
```

Registrar como job en `worker.py`:

```python
def handle_poll_cancellations(payload, context):
    from services.cancellation.status import poll_pending_cancellations
    stats = poll_pending_cancellations(limit=payload.get("limit", 100))
    logger.info("Cancellation polling stats: %s", stats)

handlers["poll_cancellations"] = handle_poll_cancellations
```

Y añadir a `cron` (o documentar en README cómo invocarlo cada hora).

### Paso 7 — Badge de estado en el listado y detalle

En el listado de facturas emitidas (`templates/partials/issued_list.html`), añadir badge cuando `cancellation_status` esté presente:

```javascript
const cancelStatus = row.cancellation_status || '';
const cancelBadge = {
  'pending':  '<span class="badge badge--warn badge--xs">⏳ Cancelación pendiente</span>',
  'accepted': '<span class="badge badge--danger badge--xs">✗ Cancelada</span>',
  'rejected': '<span class="badge badge--info badge--xs">↩ Cancelación rechazada</span>',
  'expired':  '<span class="badge badge--danger badge--xs">✗ Cancelada (72h)</span>',
}[cancelStatus] || '';
```

En el detalle del CFDI (`templates/portal_cfdi_detail.html`), si `cancellation_status == 'pending'`, mostrar banner:

```html
{% if cfdi.cancellation_status == 'pending' %}
<div class="info-banner info-banner--warn">
  ⏳ Cancelación enviada al SAT — esperando al receptor (hasta 72 horas).
  Solicitada el {{ cfdi.cancellation_requested_at[:10] }}.
</div>
{% endif %}
```

### Paso 8 — Tests

Crear `tests/test_cancellation_flow.py`:

```python
"""Tests for cancellation + substitution flow."""
import pytest
from unittest.mock import patch

from services.cancellation.service import cancel_invoice, substitute_and_cancel
from services.cancellation.types import Motivo, CancellationStatus


def test_motivo_01_requires_substitute_uuid():
    with pytest.raises(ValueError, match="sustitución"):
        cancel_invoice(
            issuer_id=11, user_id=1, cfdi_uuid="abc",
            motivo=Motivo.ERROR_CON_RELACION, substitute_uuid=None,
        )


def test_status_pending_when_invoice_over_5000(test_issuer_with_invoice):
    """Invoices > $5,000 should result in 'pending' status, waiting for receptor."""
    with patch("services.cancellation.service.cancel_via_facturapi") as mock:
        mock.return_value = {"status": "pending"}
        result = cancel_invoice(
            issuer_id=test_issuer_with_invoice["issuer_id"],
            user_id=1,
            cfdi_uuid=test_issuer_with_invoice["uuid"],
            motivo=Motivo.NO_OPERACION,
        )
        assert result["status"] == "pending"
        assert result["requires_receptor_acceptance"] is True


def test_status_accepted_when_invoice_under_5000():
    """Small invoices don't need receptor acceptance — auto-accepted."""
    # ... similar pattern


def test_substitute_and_cancel_emits_then_cancels(test_issuer_with_invoice):
    """The two-step flow: emit new with TipoRelacion 04, then cancel original."""
    with patch("facturapi_client.create_invoice") as mock_create, \
         patch("services.cancellation.service.cancel_via_facturapi") as mock_cancel:
        mock_create.return_value = {"uuid": "new-uuid-123", "id": "fac_new"}
        mock_cancel.return_value = {"status": "canceled"}

        result = substitute_and_cancel(
            issuer_id=test_issuer_with_invoice["issuer_id"],
            user_id=1,
            original_uuid=test_issuer_with_invoice["uuid"],
            new_cfdi_payload={"type": "I", "customer": {}, "items": []},
        )
        # Verify TipoRelacion 04 was injected
        call_payload = mock_create.call_args[0][2]
        assert call_payload["related_documents"][0]["relationship"] == "04"
        assert call_payload["related_documents"][0]["documents"][0]["uuid"] == test_issuer_with_invoice["uuid"]
        # Verify cancel was called with substitute_uuid
        assert mock_cancel.call_args.kwargs["substitution"] == "new-uuid-123"
        assert result["substitute_uuid"] == "new-uuid-123"


def test_polling_marks_expired_after_72h(test_issuer_with_pending):
    """After 72h, pending cancellations auto-resolve to 'expired'."""
    # ... mock the SAT response and elapsed time
```

Y test del frontend (rutas):

```python
def test_cancel_route_returns_json(client, test_issuer_with_cookie, test_invoice):
    resp = client.post(
        f"/portal/invoices/{test_invoice['uuid']}/cancel",
        data={"csrf_token": csrf_token, "motivo": "03"},
        cookies=test_issuer_with_cookie["cookie"],
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_substitute_form_route_renders_with_prefill(client, test_issuer_with_cookie, test_invoice):
    resp = client.get(
        f"/portal/invoices/{test_invoice['uuid']}/substitute",
        cookies=test_issuer_with_cookie["cookie"],
    )
    assert resp.status_code == 200
    assert test_invoice["customer_rfc"] in resp.text
    assert "Emitir reemplazo" in resp.text
```

### Paso 9 — QA manual

1. **Cancelar sin reemplazo**: factura de prueba < $5,000 → click "Cancelar sin reemplazo" → confirma → verifica que status pasa a 'accepted' inmediatamente.
2. **Cancelar sin reemplazo > $5,000**: status debe quedar 'pending' y mostrar banner de "Esperando receptor".
3. **Cancelar y emitir nueva**: click → se abre form prellenado → editar algo (ej. cambiar el precio) → "Emitir reemplazo" → verifica que se timbró la nueva con `related_documents` TipoRelacion 04 → la original quedó con `cancellation_status='pending'` o 'accepted'.
4. **Cancelar con existente**: emitir 2 facturas a propósito → en la primera, "Cancelar y sustituir con otra ya emitida" → picker muestra la segunda → seleccionar → verifica.
5. **Polling**: invocar `python worker.py --once` después de crear una cancelación pendiente → verifica que actualizó el status.

---

## Acceptance criteria

- [ ] Migración 067 aplicada idempotente
- [ ] Columnas `cancellation_status`, `cancellation_motivo`, `cancellation_substitute_uuid`, etc. existen en `sat_cfdi`
- [ ] Tabla `cancellation_log` existe
- [ ] `services/cancellation/` con los módulos descritos
- [ ] Función `cancel_invoice()` cancela vía Facturapi y persiste estado correcto
- [ ] Función `substitute_and_cancel()` ejecuta los 2 pasos en orden (emitir → cancelar)
- [ ] Si la emisión de sustituta falla, NO se cancela la original
- [ ] Si la sustituta se emite OK pero la cancelación falla, se devuelve el UUID emitido para permitir retry manual
- [ ] Ruta POST `/portal/invoices/{uuid}/cancel` funciona para los 3 casos
- [ ] Ruta GET `/portal/invoices/{uuid}/substitute` renderea form prellenado
- [ ] Ruta POST `/portal/invoices/{uuid}/submit-substitute` ejecuta el flujo de 2 pasos
- [ ] API search devuelve solo facturas vigentes del mismo emisor, excluyendo la original
- [ ] Modal de cancelación reemplazado con las 3 cards en `portal_cfdi_detail.html`
- [ ] Modal "Cancelar sin reemplazo" muestra warning de 72h si total > $5,000
- [ ] Modal "Cancelar con existente" tiene buscador en vivo
- [ ] Badge "Cancelación pendiente" aparece en el listado y detalle
- [ ] Job `poll_cancellations` registrado en worker y poleable
- [ ] Polling marca como `expired` después de 72h sin respuesta del receptor
- [ ] Tests pasan (`tests/test_cancellation_flow.py`)
- [ ] `.venv/bin/pytest -q` no introduce nuevas fallas (baseline = 12 pre-existentes)
- [ ] `.venv/bin/python -c "import app"` sigue limpio

## Logging requerido

Al final del job, escribir `context/implement/2026-06-15-cancellation-substitution-flow.md` con:

- Lista de archivos creados/modificados
- Resumen de cómo se reusa `build_facturapi_payload` (si fue extraído de `routers/invoicing.py`)
- Resultado de pytest (passed/failed)
- Cualquier desviación del plan y por qué
- Limitaciones conocidas (ej. polling cron no instalado automáticamente)

## Notas para el ejecutor autónomo

- **No hacer commit** sin que el usuario lo pida explícitamente
- Si la API de Facturapi para cancelación tiene un endpoint distinto al asumido, ajustar `facturapi_client.py` y documentar
- Si `build_facturapi_payload` no se puede extraer de forma limpia (lógica muy enredada en `_submit_impl`), añadir un parámetro opcional `related_documents_override` a `_submit_impl` y reusarla directamente
- Asegurarse de que el form prellenado para sustitución no pierda items del original (los `invoice_items` deben pasar al template)
- El picker de "existente" debe excluir la propia factura que se está cancelando
- Lenguaje en código: inglés. UI: español MX.
