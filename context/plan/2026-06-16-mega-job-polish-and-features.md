# MEGA JOB FINAL — Polish + Features autónomos

**Fecha:** 2026-06-16
**Owner:** David
**Tipo:** Multi-phase polish + features (10 fases)
**Duración estimada:** 10–18 horas autónomas
**Modo:** Autónomo extendido — el usuario estará ausente. Ejecutar todas las fases. Si una falla parcialmente, documentar y seguir.

---

## Contexto

Después de 2 mega jobs ya tienes ~95% de features Tier 1 + Tier 2 listas. Faltan 3 grupos:

1. **Polish de 6 TODOs deferidos** del mega job previo
2. **Features autónomas** que no requieren decisión del usuario (team invites, quotations→factura, mobile responsive)
3. **Quality-of-life** general (email templates con contenido real, empty states, error boundaries, admin tools internos)

**Excluido (requiere decisión del usuario):**
- Nombre del SaaS / dominio
- Conexión Resend producción
- Landing page / sitio público
- Términos legales
- Deployment a producción
- Stripe live mode

## Restricciones globales

- **Idempotencia** en migraciones
- **No breaking changes** en rutas existentes
- **Baseline tests**: 14 fallas pre-existentes — no introducir nuevas
- **No commits** sin permiso explícito
- **Reusar abstracciones existentes**: email, jobs, audit log, compute_net_totals
- **Sleek consistent design**: hairlines, tabular-nums, `--accent`, `--border`, `--surface-2`
- **Lenguaje código: inglés. UI: español MX.**

---

# FASE 1 — Conectar Lista 69-B al flujo de timbrado (30 min)

Hoy `is_rfc_blocked()` y `is_rfc_warned()` existen pero no se invocan en el timbrado real.

## Pasos

### 1.1 — Validación en `_submit_impl`

En `routers/invoicing.py` antes de llamar a Facturapi, después de validar el cliente:

```python
from services.sat.lista_69b import is_rfc_blocked, is_rfc_warned

# Validate against 69-B list before stamping
if customer_rfc and customer_rfc.upper() not in ("XAXX010101000", "XEXX010101000"):
    block_info = is_rfc_blocked(customer_rfc.upper())
    if block_info:
        log_action(request, "stamp_blocked_69b",
                   issuer_id=issuer["id"], customer_rfc=customer_rfc,
                   situacion=block_info.get("situacion"))
        raise HTTPException(
            status_code=400,
            detail=(
                f"⚠ El RFC {customer_rfc} está en la Lista 69-B del SAT como "
                f"'{block_info['situacion']}'. No se puede emitir CFDI a este receptor. "
                "Verifica con el SAT antes de continuar."
            ),
        )
    warn_info = is_rfc_warned(customer_rfc.upper())
    if warn_info:
        log_action(request, "stamp_warned_69b",
                   issuer_id=issuer["id"], customer_rfc=customer_rfc,
                   situacion=warn_info.get("situacion"))
        # Continue but log — could surface as a warning in the future
```

### 1.2 — Badge "69-B" en lista de clientes

En `templates/portal_clients.html` (o el partial equivalente del listado):
- Agregar query a `sat_lista_69b` cuando se carga la lista de clientes
- Si el RFC está en la lista, mostrar badge rojo o amarillo según situación

### 1.3 — Tests

Ampliar `tests/test_lista_69b.py`:
- `test_submit_blocked_when_rfc_in_69b_definitivo`
- `test_submit_warned_when_rfc_in_69b_presunto`  
- `test_submit_allows_generic_rfcs` (XAXX, XEXX no se filtran)

## Acceptance

- [ ] Timbrado bloqueado para RFCs Definitivo
- [ ] Audit log captura intentos bloqueados
- [ ] Badge visible en customers list
- [ ] Tests pasan

---

# FASE 2 — Banners persistentes (trial/uso + onboarding) (1 h)

## Pasos

### 2.1 — Servicio `services/banners/`

```
services/banners/
├── __init__.py
├── trial_banner.py    # compute_trial_banner_state(issuer_id) → dict
├── usage_banner.py    # compute_usage_banner_state(issuer_id) → dict
└── onboarding_banner.py  # compute_onboarding_banner_state(issuer_id) → dict
```

Cada uno devuelve `{visible, variant, title, message, cta_url, cta_label}` o `None`.

### 2.2 — Helper en `routers/portal/_helpers.py`

Agregar `get_portal_banners(issuer_id)` que retorna lista de banners activos. Inyectar en el context de TODAS las páginas portal:

```python
def get_portal_context(issuer_id):
    from services.banners import (
        compute_trial_banner_state,
        compute_usage_banner_state,
        compute_onboarding_banner_state,
    )
    banners = []
    for fn in (
        compute_onboarding_banner_state,
        compute_trial_banner_state,
        compute_usage_banner_state,
    ):
        b = fn(issuer_id)
        if b:
            banners.append(b)
    return {"banners": banners}
```

### 2.3 — Template `templates/components/portal_banners.html`

```html
{% for b in banners %}
<div class="portal-banner portal-banner--{{ b.variant }}" role="alert">
  <div class="portal-banner__icon">
    {% if b.variant == 'danger' %}⚠{% elif b.variant == 'warn' %}⏰{% else %}ℹ{% endif %}
  </div>
  <div class="portal-banner__body">
    <strong>{{ b.title }}</strong>
    <span>{{ b.message }}</span>
  </div>
  {% if b.cta_url %}
    <a href="{{ b.cta_url }}" class="portal-banner__cta">{{ b.cta_label }}</a>
  {% endif %}
  {% if b.dismissable %}
    <button class="portal-banner__close" data-dismiss-banner="{{ b.key }}">×</button>
  {% endif %}
</div>
{% endfor %}
```

Incluir en `templates/base_portal.html` justo después del header.

### 2.4 — Estilos sleek

```css
.portal-banner {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 16px; border-radius: 8px; margin: 0 0 12px;
  border: 1px solid;
}
.portal-banner--info { background: rgba(99,102,241,.08); border-color: rgba(99,102,241,.25); color: #4338ca; }
.portal-banner--warn { background: rgba(245,158,11,.08); border-color: rgba(245,158,11,.3); color: #92400e; }
.portal-banner--danger { background: rgba(239,68,68,.08); border-color: rgba(239,68,68,.3); color: #991b1b; }
.portal-banner__icon { font-size: 18px; flex-shrink: 0; }
.portal-banner__body { flex: 1; min-width: 0; font-size: 13px; }
.portal-banner__body strong { display: block; margin-bottom: 2px; }
.portal-banner__cta {
  font-size: 13px; font-weight: 600; padding: 6px 12px;
  border-radius: 6px; background: rgba(255,255,255,.6);
  text-decoration: none; color: inherit; border: 1px solid currentColor;
}
.portal-banner__close { background: none; border: 0; font-size: 18px; color: inherit; cursor: pointer; opacity: .6; }
```

### 2.5 — Dismiss persistente

Usar `ui_dismissals` table existente. JS lee y posta a `POST /portal/api/dismiss-banner`.

### 2.6 — Tests

`tests/test_portal_banners.py`:
- Banner trial aparece según días restantes
- Banner uso aparece al 80% y 100%
- Banner onboarding aparece si step < 5 y no dismissed
- Dismiss persiste

## Acceptance

- [ ] 3 servicios de banners funcionando
- [ ] Banners visibles en todas las páginas portal
- [ ] Dismiss persiste vía ui_dismissals
- [ ] Tests pasan

---

# FASE 3 — Plantillas de email con contenido real (1 h)

Las plantillas existen pero algunas tienen contenido mínimo. Mejorarlas con HTML cuidado y placeholder branding intercambiable.

## Pasos

### 3.1 — Actualizar plantillas existentes

Revisar y mejorar:
- `templates/emails/trial_expiring.html` — tabla de plan + CTA destacado
- `templates/emails/payment_failed.html` — explicación amable + link a actualizar tarjeta
- `templates/emails/declaration_summary.html` — diseño tipo "tarjeta fiscal" con saldo/línea/vencimiento
- `templates/emails/invoice_sent.html` — emisor destacado + monto grande + adjuntos listados
- `templates/emails/welcome.html` — paso a paso de qué hacer primero

### 3.2 — Versiones .txt (plain text)

Crear versión `.txt` por cada `.html` para clientes que no renderean HTML.

### 3.3 — Test de rendering

`tests/test_email_templates_content.py`:
- Cada template renderea sin errores
- Contiene placeholders correctos (`{{ brand_name }}`, etc.)
- Versión texto es legible

### 3.4 — Smoke render script

Script `scripts/render_email_samples.py` que renderea cada plantilla con datos mock y guarda en `tmp/email_samples/` para revisión visual.

## Acceptance

- [ ] 9 plantillas con HTML pulido
- [ ] Versiones .txt para todas
- [ ] Script de samples funciona
- [ ] Tests pasan

---

# FASE 4 — Team invites + permisos enforcados (3-4 h)

La tabla `memberships` existe con roles `owner/accountant/viewer/admin` pero falta:
- UI para invitar
- Aceptación de invitación por email
- Validación real de permisos por ruta

## Pasos

### 4.1 — Migración 073

```sql
CREATE TABLE IF NOT EXISTS membership_invites (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  invited_by_user_id INTEGER NOT NULL,
  email TEXT NOT NULL,
  role TEXT NOT NULL,                  -- accountant, viewer, admin
  token TEXT NOT NULL UNIQUE,
  expires_at TEXT NOT NULL,
  accepted_at TEXT,
  accepted_by_user_id INTEGER,
  status TEXT NOT NULL DEFAULT 'pending',  -- pending, accepted, expired, revoked
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_membership_invites_email ON membership_invites(email, status);
CREATE INDEX IF NOT EXISTS idx_membership_invites_token ON membership_invites(token);
```

### 4.2 — Servicio `services/team/`

```
services/team/
├── __init__.py
├── invites.py      # create_invite, accept_invite, revoke_invite, list_invites
├── permissions.py  # require_role, has_permission
└── members.py      # list_members, change_role, remove_member
```

`permissions.py`:

```python
"""Role-based permission checks.

Hierarchy: viewer < accountant < admin < owner
"""
ROLE_ORDER = {"viewer": 0, "accountant": 1, "admin": 2, "owner": 3}

ACTION_REQUIREMENTS = {
    "issue_invoice": "accountant",
    "cancel_invoice": "accountant",
    "edit_issuer_settings": "admin",
    "upload_fiel": "owner",
    "upload_csd": "owner",
    "manage_billing": "owner",
    "invite_member": "admin",
    "remove_member": "owner",
    "change_member_role": "owner",
    "view_audit_log": "admin",
}


def has_permission(user_role: str, action: str) -> bool:
    required = ACTION_REQUIREMENTS.get(action, "owner")
    return ROLE_ORDER.get(user_role, -1) >= ROLE_ORDER[required]


def require_permission(action: str):
    """Decorator/dependency for FastAPI routes."""
    from fastapi import HTTPException
    def checker(request):
        role = getattr(request.state, "membership_role", "viewer")
        if not has_permission(role, action):
            raise HTTPException(403, detail=f"Tu rol ({role}) no permite esta acción.")
    return checker
```

### 4.3 — UI: página `/portal/team`

`templates/portal_team.html`:
- Tabla de miembros actuales con rol editable (solo owner puede cambiar)
- Sección "Invitar nuevo miembro" con form: email + rol
- Tabla de invitaciones pendientes con acción "Revocar"
- Sleek consistent con el portal

### 4.4 — Aceptación de invitación

Ruta `GET /accept-invite/{token}` que:
- Si el usuario está logueado y el email coincide → acepta + redirect a portal home
- Si está logueado pero el email no coincide → muestra mensaje
- Si no está logueado → muestra form de registro/login pre-llenado con el email

### 4.5 — Email de invitación

Usar el sistema existente. Plantilla `templates/emails/team_invite.html`:

```html
{% extends "base.html" %}
{% block email_content %}
<h2>Te invitaron a {{ brand_name }}</h2>
<p><strong>{{ inviter_name }}</strong> te invitó a colaborar como <strong>{{ role_label }}</strong> en la cuenta de <strong>{{ issuer_name }}</strong>.</p>
<p><a href="{{ accept_url }}" class="button">Aceptar invitación</a></p>
<p class="muted">Este link expira el {{ expires_at }}.</p>
{% endblock %}
```

### 4.6 — Enforcement de permisos en rutas críticas

Agregar `Depends(require_permission(...))` o checks dentro de las rutas:
- Cancelar factura → accountant+
- Editar settings → admin+
- Upload FIEL/CSD → owner
- Manage billing → owner
- View audit log → admin+
- Invite member → admin+

### 4.7 — Tests

`tests/test_team_invites.py`:
- Crear invite + aceptar funciona
- Token expirado falla
- Email mismatch falla
- Revoke funciona

`tests/test_permissions.py`:
- Roles vs acciones (tabla completa)
- 403 cuando rol insuficiente

## Acceptance

- [ ] Migración 073 aplicada
- [ ] `/portal/team` funcional para owners/admins
- [ ] Email de invitación se encola
- [ ] Aceptación crea membership correctamente
- [ ] Permisos enforcados en 6+ rutas críticas
- [ ] Tests pasan

---

# FASE 5 — Quotations → Factura conversion (2 h)

La tabla `quotations` existe. Falta el botón "Convertir a factura" que prellena el form de creación.

## Pasos

### 5.1 — Inspeccionar estado actual

Leer `services/quotations.py`, `routers/portal/quotations.py`, templates de quotation. Identificar cómo se cargan los items.

### 5.2 — Endpoint de conversión

`GET /portal/quotations/{id}/convert-to-invoice` → redirige a `/portal/create?quote_id={id}` (ya existe el handling en `portal_create`, verificar).

### 5.3 — Botón en la vista de cotización

En `templates/portal_quotation_detail.html` (o equivalente) agregar:

```html
{% if quote.status != 'converted' %}
<a href="/portal/quotations/{{ quote.id }}/convert-to-invoice" class="btn btn--primary">
  Convertir a factura
</a>
{% endif %}
```

### 5.4 — Marcar cotización como convertida

Cuando el `submit_impl` recibe `quote_id`, después de timbrar:
```python
if quote_id:
    conn.execute(
        "UPDATE quotations SET status = 'converted', converted_invoice_id = ?, converted_at = datetime('now') WHERE id = ?",
        (invoice_local_id, quote_id),
    )
```

### 5.5 — Migración 074 (si necesaria)

```sql
ALTER TABLE quotations ADD COLUMN converted_invoice_id INTEGER;
ALTER TABLE quotations ADD COLUMN converted_at TEXT;
```

### 5.6 — UI: link a la factura desde quotation convertida

Si `status='converted'`, mostrar "Esta cotización se facturó el {fecha} → [Ver factura]".

### 5.7 — Tests

`tests/test_quotation_conversion.py`:
- Crear quotation → convertir → factura tiene los items correctos
- Quotation queda con status='converted'

## Acceptance

- [ ] Botón visible en detalle de quotation
- [ ] Conversión funciona end-to-end
- [ ] Quotation marcada como converted
- [ ] Link a factura visible
- [ ] Tests pasan

---

# FASE 6 — Mobile responsive polish (2-3 h)

El portal funciona en desktop. En móvil hay tablas que se quiebran, forms muy anchos, navegación dificil.

## Pasos

### 6.1 — Audit de las 8 vistas más críticas

1. Dashboard (`/portal/home`)
2. Crear factura (`/portal/create`)
3. Listado emitidas (`/portal/invoices/issued`)
4. Listado recibidas (`/portal/invoices/received`)
5. Detalle CFDI
6. Settings (4 tabs)
7. Reportes mensual/anual
8. Onboarding wizard

### 6.2 — Breakpoints estándar

```css
@media (max-width: 768px) { /* tablet */ }
@media (max-width: 480px) { /* phone */ }
```

### 6.3 — Tablas responsive

Para tablas grandes (issued/received list), convertir a "cards stack" en móvil:

```css
@media (max-width: 768px) {
  table.responsive-stack thead { display: none; }
  table.responsive-stack tr {
    display: block; padding: 12px; border: 1px solid var(--border);
    border-radius: 8px; margin-bottom: 8px; background: var(--surface);
  }
  table.responsive-stack td {
    display: flex; justify-content: space-between;
    padding: 4px 0; border: 0;
  }
  table.responsive-stack td::before {
    content: attr(data-label); font-weight: 600; color: var(--text-muted);
  }
}
```

Aplicar `class="responsive-stack"` y `data-label="..."` en celdas relevantes.

### 6.4 — Sidebar colapsable en móvil

Si no está, agregar hamburger button que abre el sidebar como overlay.

### 6.5 — Forms en columna única

Los `.row` con 2 columnas pasan a 1 en móvil. La mayoría del CSS ya lo hace, verificar y corregir donde falte.

### 6.6 — Modales fullscreen en móvil

```css
@media (max-width: 480px) {
  .modal-panel, .form-modal__panel { width: 100vw; height: 100vh; border-radius: 0; }
}
```

### 6.7 — Cards resumen apiladas

Los grids de 4 cards → apilarse en móvil:

```css
@media (max-width: 480px) {
  .resumen-cards { grid-template-columns: 1fr 1fr; }
}
```

### 6.8 — Tests visuales

Aunque no podemos hacer screenshot tests reales, podemos validar que el HTML/CSS no tiene errores con un linter mínimo. Documentar manualmente qué pantallas se ajustaron.

## Acceptance

- [ ] CSS responsive aplicado en 8 vistas principales
- [ ] Sidebar colapsable en mobile
- [ ] Tablas convertidas a cards stack en mobile
- [ ] Modales fullscreen en phone
- [ ] Documentado qué cambió en el log

---

# FASE 7 — Quality of life UX (1-2 h)

Mejoras pequeñas pero acumulativas.

## Pasos

### 7.1 — Empty states sleek

Crear `templates/components/empty_state.html`:

```html
{% macro empty_state(icon, title, description, cta_url=None, cta_label=None) %}
<div class="empty-state">
  <div class="empty-state__icon">{{ icon }}</div>
  <h3 class="empty-state__title">{{ title }}</h3>
  <p class="empty-state__description">{{ description }}</p>
  {% if cta_url %}
    <a href="{{ cta_url }}" class="btn btn--primary">{{ cta_label }}</a>
  {% endif %}
</div>
{% endmacro %}
```

Aplicar en las vistas que muestran listas vacías: facturas, declaraciones, cotizaciones, clientes, productos.

### 7.2 — Loading states consistentes

Skeleton loaders para tablas que cargan vía API. Reusar lo que ya exista en `static/css/portal.css`.

### 7.3 — Error boundaries amigables

En lugar de stack traces, mostrar mensajes humanos. Validar que el handler existe.

### 7.4 — Confirmaciones para acciones destructivas

Modal de confirmación uniforme para: eliminar cliente, eliminar producto, cancelar factura sin reemplazo. Crear macro `confirm_modal()`.

### 7.5 — Toasts uniformes

Verificar que `window.portalToast` se usa consistentemente. Reemplazar `alert()` con toasts donde queden.

### 7.6 — Atajos de teclado

- `Cmd/Ctrl+K` → quick search/command palette (puede ser básico)
- `Esc` → cierra modales
- `N` → nueva factura (en vistas donde aplique)

## Acceptance

- [ ] Macro empty_state aplicado en 5+ vistas
- [ ] Confirmaciones uniformes en acciones destructivas
- [ ] Atajos de teclado básicos funcionan
- [ ] Ningún `alert()` queda en el código

---

# FASE 8 — Help Center / Documentation interna (1-2 h)

Páginas de ayuda para usuarios dentro del portal.

## Pasos

### 8.1 — Estructura

`/portal/guides` ya existe. Verificar y expandir contenido.

Crear/poblar páginas para:
- "¿Cómo emito mi primera factura?"
- "¿Qué es una PPD y un complemento de pago?"
- "¿Qué hago si necesito cancelar una factura?"
- "¿Qué es una nota de crédito y cuándo emitirla?"
- "¿Cómo funcionan las facturas con cliente extranjero?"
- "Glosario fiscal: PUE, PPD, CFDI, REP, RFC, CSD, FIEL, manifesto"
- "Errores comunes del SAT y cómo resolverlos"

### 8.2 — Markdown rendering

Si no hay aún, agregar un renderizador de Markdown sencillo para que el contenido sea editable como `.md`.

### 8.3 — Búsqueda en guías

Buscador simple que filtre por título/contenido.

### 8.4 — Link contextual

Desde puntos clave del portal, links "¿Necesitas ayuda?" → guía relevante.

## Acceptance

- [ ] 7 guías escritas
- [ ] Markdown rendering funciona
- [ ] Búsqueda funciona
- [ ] Links contextuales en 3+ páginas

---

# FASE 9 — Admin tools internos (1-2 h)

Para ti (David) como dueño de la plataforma, vista cross-tenant para monitorear el negocio.

## Pasos

### 9.1 — Detección de admin

`is_platform_admin(user_id)` chequea si el usuario es el dueño de la plataforma. Definir vía env var `PLATFORM_ADMIN_EMAILS=venegasdavid98@gmail.com`.

### 9.2 — Rutas `/admin/*`

- `/admin/dashboard` — KPIs: # de emisores activos, # facturas timbradas (último 30d), MRR (de Stripe), trials activos, suscripciones próximas a expirar
- `/admin/issuers` — listado de todos los emisores con filtros
- `/admin/issuers/{id}` — detalle de un emisor con su uso
- `/admin/declarations-stats` — cuántas declaraciones procesadas, por contador
- `/admin/system-health` — # de jobs en cola, errores recientes, ultima ejecución de crons

### 9.3 — Templates admin

Reusar `base_admin.html` si existe. Sleek, tabular-nums.

### 9.4 — Tests

`tests/test_admin_dashboard.py`:
- Acceso bloqueado para non-admin
- Métricas se computan correctamente

## Acceptance

- [ ] `/admin/dashboard` con 5+ KPIs
- [ ] Solo accesible para PLATFORM_ADMIN_EMAILS
- [ ] Listado de emisores con búsqueda
- [ ] System health visible

---

# FASE 10 — Validación parser de constancia con PDFs reales sintéticos (30 min)

Generar PDFs sintéticos que imiten formato real del SAT y validar el parser.

## Pasos

### 10.1 — Generar fixtures

`tests/fixtures/constancias/` con PDFs generados via `reportlab` que imiten:
- Constancia PF (RFC 13 chars, CURP, régimen 612)
- Constancia PM (RFC 12 chars, sin CURP, régimen 601)
- Constancia RESICO (régimen 626)
- Constancia con obligaciones múltiples
- Edge case: campos mal formateados

### 10.2 — Tests de extracción

`tests/test_constancia_real_format.py`:
- Cada fixture parsea con confidence >= 0.8
- Campos clave (RFC, razón social, régimen, CP) se extraen correctamente

### 10.3 — Documentar limitaciones

Lo que SÍ se puede extraer vs lo que requeriría LLM (en notas).

## Acceptance

- [ ] 5 PDFs fixture generados
- [ ] Parser logra confidence > 0.8 en al menos 4/5
- [ ] Tests pasan

---

## Logging consolidado al final

Escribir `context/implement/2026-06-16-mega-job-polish-and-features.md` con:

- Tabla resumen por fase: Estado | Tests | Archivos
- Decisiones tomadas y desviaciones
- Resultado pytest final
- TODOs que quedaron (idealmente cero)
- Sugerencia de qué validar manualmente cuando el usuario regrese

---

## Orden de ejecución sugerido

Ejecutar las fases EN ORDEN. Fases independientes en caso de fallo:
- Si Fase 1 falla, sigue a Fase 2
- Si Fase 4 (team invites) requiere decisiones complejas, hacer MVP minimal y documentar
- Las fases 6 y 7 (mobile + UX) son más estéticas — si tiempo escaso, priorizar 6.1-6.4

## Notas críticas para el ejecutor autónomo

- **NO HACER COMMITS** — el usuario verá los cambios y decidirá
- **Si algo rompe tests existentes, arréglalo antes de continuar**
- **Si una librería no está instalada**, agregar a `requirements.txt` e instalar
- **Reusar abstracciones**: `services/email/queue.py`, `services/jobs.py`, `services/banners/`, `compute_net_totals`
- **Si una fase requiere decisión de copy/marca**, usar placeholders genéricos ("ContaNeta") y documentar
- **No introducir nuevas dependencias pesadas** — Markdown rendering puede ser `markdown-it-py` o regex simple si no hay nada
- **Documentar cualquier deviación del plan** en el log final
- **Si Fase X tarda > 3h, hacer versión MVP y documentar lo simplificado**

Tiempo objetivo: 10-18 horas autónomas. Si termina antes, está bien. Si toma más, está bien.
