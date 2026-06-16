# Job: Scaffolding completo del sistema de email transaccional

**Fecha:** 2026-06-15
**Owner:** David
**Tipo:** Foundation / infrastructure (preparar para Resend sin depender de dominio aún)
**Duración estimada:** 1–1.5 días autónomos
**Modo:** Autónomo — ejecutar de corrido. Si encuentras un bloqueador, documéntalo en el log y sigue con el siguiente paso.

---

## Contexto

ContaNeta va a enviar emails transaccionales (facturas a clientes finales, declaraciones, recordatorios, alertas de certificados). El proveedor elegido es **Resend** ($0 hasta 3,000 correos/mes, $20 por 50,000 después). El dominio definitivo aún no está decidido, así que este job NO requiere comprar dominio ni configurar DNS — solo deja todo listo para que cuando el dominio esté, sea un swap de variables de entorno + verificación en Resend (15 minutos).

El sistema debe:

- Funcionar en modo "noop" en desarrollo sin API key real (loguea pero no manda)
- Tener una abstracción de proveedor (hoy Resend, mañana puede cambiar)
- Registrar TODO en una tabla `email_log` para auditoría
- Procesar envíos de forma asíncrona vía la cola `services/jobs.py` que ya existe
- Recibir webhooks de Resend (delivered, bounced, opened) en un endpoint
- Tener plantillas HTML con placeholders de marca intercambiables

Trigger points (donde se debe disparar el envío) **se marcan con TODO** en este job — la lógica real de invocar `send_email()` desde cada flujo (timbrado, registro, etc.) NO se implementa aquí. Eso va en un job posterior.

## Restricciones

- **No tocar URLs existentes ni hacer breaking changes**.
- **Migración idempotente** con `ADD COLUMN IF NOT EXISTS` y `CREATE TABLE IF NOT EXISTS`.
- **Sin dependencias nuevas pesadas**: usar `httpx` (ya en el proyecto) para llamar a Resend, no añadir un SDK.
- **El modo noop debe ser el default** cuando no hay `RESEND_API_KEY` configurado — esto permite que dev/tests no manden correos reales.
- **Tests verdes antes y después**: `.venv/bin/pytest -q` debe quedar igual o mejor que la baseline (12 fallas pre-existentes documentadas en `test_facturapi_provision`, `test_fiscal_route`, `test_portal_manifesto`, `test_sat_cron_tiers`).
- **No tocar `services/email_sender.py` ni `services/email_templates.py`** existentes — los analizamos y construimos encima sin romperlos. Si su API es buena, la reusamos. Si no, los wrappeamos.
- **Lenguaje en código: inglés. Lenguaje en plantillas/UI: español MX.**

---

## Plan de implementación (en orden)

### Paso 0 — Analizar lo que ya existe

Antes de tocar nada, leer:
- `services/email_sender.py`
- `services/email_templates.py`
- `services/jobs.py` (cómo funciona la cola)
- `worker.py` (cómo se registran handlers)
- `routers/auth/register.py` (donde ya hay verificación de email)

Documentar en el log de implementación qué API exponen y si vale reusarlas o wrappear. Decidir basado en eso si se renombra/refactoriza o se construye lado a lado.

### Paso 1 — Migración 066: email_log + toggles

Archivo: `migrations/066_email_system.sql`

```sql
-- Migration 066: email_log table + per-issuer/customer toggles
-- Allows tracking all transactional emails (invoice, declaration, alerts)
-- and lets issuers/customers opt out of auto-sending.

CREATE TABLE IF NOT EXISTS email_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER,
  user_id INTEGER,
  email_type TEXT NOT NULL,              -- 'invoice_sent', 'declaration_summary', 'welcome', etc.
  related_object_type TEXT,              -- 'invoice', 'declaration', 'user', NULL
  related_object_id INTEGER,
  to_email TEXT NOT NULL,
  to_name TEXT,
  from_email TEXT,
  from_name TEXT,
  reply_to TEXT,
  subject TEXT,
  template TEXT,                          -- template name used, e.g. 'invoice_sent'
  provider TEXT,                          -- 'resend', 'noop', 'postmark', etc.
  provider_message_id TEXT,               -- ID returned by provider for tracking
  status TEXT NOT NULL DEFAULT 'queued',  -- queued, sent, delivered, bounced, failed, opened, clicked
  error_message TEXT,
  payload_json TEXT,                      -- snapshot of context vars used to render
  sent_at TEXT,
  delivered_at TEXT,
  opened_at TEXT,
  clicked_at TEXT,
  bounced_at TEXT,
  failed_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_email_log_issuer_created
  ON email_log(issuer_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_log_status
  ON email_log(status);
CREATE INDEX IF NOT EXISTS idx_email_log_provider_msg
  ON email_log(provider_message_id);
CREATE INDEX IF NOT EXISTS idx_email_log_related
  ON email_log(related_object_type, related_object_id);

-- Per-issuer toggle: master kill-switch for transactional emails
ALTER TABLE issuers ADD COLUMN email_notifications_enabled INTEGER NOT NULL DEFAULT 1;

-- Per-customer toggle: don't auto-send invoices to this client
ALTER TABLE customer_profiles ADD COLUMN auto_send_invoices INTEGER NOT NULL DEFAULT 1;
```

Verificar que `migrations_runner.py` la aplica al startup. Si `ADD COLUMN IF NOT EXISTS` no es soportado en la versión de SQLite, envolver en try/except con `PRAGMA table_info`.

### Paso 2 — Estructura de servicios

Crear carpeta `services/email/` con estos archivos:

```
services/email/
├── __init__.py         # exports públicos
├── types.py            # EmailType enum, dataclasses
├── config.py           # carga de env vars + selección de provider
├── sender.py           # send_email() público
├── log.py              # CRUD de email_log
├── templates.py        # rendering Jinja2
├── providers/
│   ├── __init__.py
│   ├── base.py         # interface Provider
│   ├── noop.py         # NoopProvider (dev sin API key)
│   └── resend.py       # ResendProvider (HTTP API)
```

**`services/email/types.py`**:

```python
"""Email system types and enums."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class EmailType(str, Enum):
    INVOICE_SENT = "invoice_sent"
    DECLARATION_SUMMARY = "declaration_summary"
    WELCOME = "welcome"
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"
    CSD_EXPIRING = "csd_expiring"
    FIEL_EXPIRING = "fiel_expiring"
    TRIAL_EXPIRING = "trial_expiring"
    SUBSCRIPTION_RENEWED = "subscription_renewed"
    PAYMENT_FAILED = "payment_failed"


class EmailStatus(str, Enum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    CLICKED = "clicked"
    BOUNCED = "bounced"
    FAILED = "failed"


@dataclass
class Attachment:
    filename: str
    content_bytes: bytes
    mime_type: str = "application/octet-stream"


@dataclass
class EmailMessage:
    """Outbound email message — all fields the providers need."""
    to_email: str
    subject: str
    html_body: str
    text_body: Optional[str] = None
    to_name: Optional[str] = None
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    reply_to: Optional[str] = None
    attachments: list[Attachment] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)  # for analytics


@dataclass
class SendResult:
    success: bool
    provider_message_id: Optional[str] = None
    error_message: Optional[str] = None
```

**`services/email/config.py`**:

```python
"""Email system configuration from env vars."""
import os
from typing import Literal

ProviderName = Literal["noop", "resend"]


def get_provider_name() -> ProviderName:
    """Return active provider. Defaults to 'noop' if RESEND_API_KEY missing."""
    explicit = os.getenv("EMAIL_PROVIDER", "").strip().lower()
    if explicit in ("noop", "resend"):
        return explicit  # type: ignore
    if os.getenv("RESEND_API_KEY"):
        return "resend"
    return "noop"


def get_default_from_address() -> str:
    return os.getenv("EMAIL_FROM_ADDRESS", "noreply@example.com")


def get_default_from_name() -> str:
    return os.getenv("EMAIL_FROM_NAME", "ContaNeta")


def get_resend_api_key() -> str:
    return os.getenv("RESEND_API_KEY", "")


def get_resend_webhook_secret() -> str:
    return os.getenv("RESEND_WEBHOOK_SECRET", "")


def is_dev_mode() -> bool:
    return os.getenv("ENV", "dev").lower() == "dev"
```

**`services/email/providers/base.py`**:

```python
"""Provider interface."""
from abc import ABC, abstractmethod
from services.email.types import EmailMessage, SendResult


class EmailProvider(ABC):
    name: str = "base"

    @abstractmethod
    def send(self, message: EmailMessage) -> SendResult: ...
```

**`services/email/providers/noop.py`**:

```python
"""Noop provider: logs but doesn't send. Used in dev without API key."""
import logging
import uuid
from services.email.providers.base import EmailProvider
from services.email.types import EmailMessage, SendResult

logger = logging.getLogger(__name__)


class NoopProvider(EmailProvider):
    name = "noop"

    def send(self, message: EmailMessage) -> SendResult:
        msg_id = f"noop-{uuid.uuid4().hex[:12]}"
        logger.info(
            "EMAIL[noop] to=%s subject=%r template attachments=%d",
            message.to_email, message.subject, len(message.attachments),
        )
        return SendResult(success=True, provider_message_id=msg_id)
```

**`services/email/providers/resend.py`**:

```python
"""Resend HTTP provider. Uses Resend REST API directly (no SDK)."""
import base64
import logging
from typing import Any

import httpx

from services.email.config import get_resend_api_key
from services.email.providers.base import EmailProvider
from services.email.types import EmailMessage, SendResult

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


class ResendProvider(EmailProvider):
    name = "resend"

    def send(self, message: EmailMessage) -> SendResult:
        api_key = get_resend_api_key()
        if not api_key:
            return SendResult(success=False, error_message="RESEND_API_KEY not configured")

        from_value = (
            f"{message.from_name} <{message.from_email}>"
            if message.from_name and message.from_email
            else (message.from_email or "")
        )
        to_value = (
            f"{message.to_name} <{message.to_email}>"
            if message.to_name
            else message.to_email
        )

        payload: dict[str, Any] = {
            "from": from_value,
            "to": [to_value],
            "subject": message.subject,
            "html": message.html_body,
        }
        if message.text_body:
            payload["text"] = message.text_body
        if message.reply_to:
            payload["reply_to"] = [message.reply_to]
        if message.tags:
            payload["tags"] = [{"name": k, "value": v} for k, v in message.tags.items()]
        if message.attachments:
            payload["attachments"] = [
                {
                    "filename": a.filename,
                    "content": base64.b64encode(a.content_bytes).decode("ascii"),
                }
                for a in message.attachments
            ]

        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.post(
                    RESEND_API_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            if resp.status_code >= 400:
                return SendResult(
                    success=False,
                    error_message=f"Resend {resp.status_code}: {resp.text[:300]}",
                )
            data = resp.json()
            return SendResult(success=True, provider_message_id=data.get("id"))
        except Exception as exc:
            logger.exception("Resend send failed")
            return SendResult(success=False, error_message=str(exc))
```

**`services/email/log.py`**:

```python
"""CRUD helpers for email_log table."""
import json
from datetime import datetime
from typing import Optional

from database import db


def insert_log(
    *,
    email_type: str,
    to_email: str,
    issuer_id: Optional[int] = None,
    user_id: Optional[int] = None,
    related_object_type: Optional[str] = None,
    related_object_id: Optional[int] = None,
    to_name: Optional[str] = None,
    from_email: Optional[str] = None,
    from_name: Optional[str] = None,
    reply_to: Optional[str] = None,
    subject: Optional[str] = None,
    template: Optional[str] = None,
    provider: Optional[str] = None,
    payload_context: Optional[dict] = None,
    status: str = "queued",
) -> int:
    """Insert a new email_log row and return its id."""
    conn = db()
    cur = conn.execute(
        """INSERT INTO email_log (
              issuer_id, user_id, email_type, related_object_type, related_object_id,
              to_email, to_name, from_email, from_name, reply_to,
              subject, template, provider, payload_json, status
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            issuer_id, user_id, email_type, related_object_type, related_object_id,
            to_email, to_name, from_email, from_name, reply_to,
            subject, template, provider,
            json.dumps(payload_context or {}, default=str),
            status,
        ),
    )
    conn.commit()
    log_id = cur.lastrowid
    conn.close()
    return log_id


def mark_sent(log_id: int, provider_message_id: Optional[str] = None) -> None:
    conn = db()
    conn.execute(
        """UPDATE email_log
              SET status = 'sent',
                  provider_message_id = COALESCE(?, provider_message_id),
                  sent_at = ?,
                  updated_at = ?
            WHERE id = ?""",
        (provider_message_id, datetime.utcnow().isoformat(), datetime.utcnow().isoformat(), log_id),
    )
    conn.commit()
    conn.close()


def mark_failed(log_id: int, error_message: str) -> None:
    conn = db()
    conn.execute(
        """UPDATE email_log
              SET status = 'failed',
                  error_message = ?,
                  failed_at = ?,
                  updated_at = ?
            WHERE id = ?""",
        (error_message[:500], datetime.utcnow().isoformat(), datetime.utcnow().isoformat(), log_id),
    )
    conn.commit()
    conn.close()


def update_status_by_provider_id(
    provider_message_id: str,
    new_status: str,
    timestamp_field: Optional[str] = None,
) -> int:
    """Update email_log entry when a webhook event arrives."""
    conn = db()
    if timestamp_field in ("delivered_at", "opened_at", "clicked_at", "bounced_at"):
        cur = conn.execute(
            f"""UPDATE email_log
                   SET status = ?,
                       {timestamp_field} = ?,
                       updated_at = ?
                 WHERE provider_message_id = ?""",
            (new_status, datetime.utcnow().isoformat(), datetime.utcnow().isoformat(), provider_message_id),
        )
    else:
        cur = conn.execute(
            """UPDATE email_log
                  SET status = ?, updated_at = ?
                WHERE provider_message_id = ?""",
            (new_status, datetime.utcnow().isoformat(), provider_message_id),
        )
    conn.commit()
    affected = cur.rowcount
    conn.close()
    return affected
```

**`services/email/templates.py`**:

```python
"""Render email templates using Jinja2 from templates/emails/."""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates" / "emails"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render(template_name: str, context: dict) -> tuple[str, str]:
    """Render an email template. Returns (html, text).

    The template must extend `base.html` and define an `email_subject` block.
    Text version is derived by stripping HTML if no `.txt` template exists.
    """
    html_template = _env.get_template(f"{template_name}.html")
    html = html_template.render(**context)
    try:
        text_template = _env.get_template(f"{template_name}.txt")
        text = text_template.render(**context)
    except Exception:
        # Fallback: derive plain text from HTML
        import re
        text = re.sub(r"<[^>]+>", "", html)
        text = re.sub(r"\s+\n", "\n", text).strip()
    return html, text


def render_subject(template_name: str, context: dict) -> str:
    """Render the `email_subject` block of a template."""
    tpl = _env.get_template(f"{template_name}.html")
    # Find the {% block email_subject %}...{% endblock %} content
    module = tpl.make_module(context)
    return getattr(module, "email_subject", lambda: "Notificación de ContaNeta")()
```

Nota: el renderizado de subject como bloque puede no funcionar directo en Jinja2 sin truco. Alternativa más simple: pasar el subject como parámetro al `send_email` o tener un dict `SUBJECTS_BY_TEMPLATE`. Si la implementación de `render_subject` es frágil, **usa el dict mapping** — más simple y predecible.

**`services/email/sender.py`**:

```python
"""Main send_email() entry point."""
import logging
from typing import Optional

from services.email import config, log, templates
from services.email.providers.base import EmailProvider
from services.email.providers.noop import NoopProvider
from services.email.providers.resend import ResendProvider
from services.email.types import Attachment, EmailMessage

logger = logging.getLogger(__name__)


SUBJECTS_BY_TEMPLATE = {
    "invoice_sent": "{from_name} te emitió una factura por ${total}",
    "declaration_summary": "Tu declaración de {periodo} está lista",
    "welcome": "Bienvenido a ContaNeta",
    "email_verification": "Verifica tu correo",
    "password_reset": "Restablecer contraseña",
    "csd_expiring": "Tu CSD vence pronto",
    "fiel_expiring": "Tu FIEL vence pronto",
    "trial_expiring": "Tu trial termina en {days} días",
    "subscription_renewed": "Suscripción renovada",
    "payment_failed": "No pudimos procesar tu pago",
}


def _get_provider() -> EmailProvider:
    name = config.get_provider_name()
    if name == "resend":
        return ResendProvider()
    return NoopProvider()


def send_email(
    *,
    to_email: str,
    template: str,
    context: dict,
    to_name: Optional[str] = None,
    reply_to: Optional[str] = None,
    attachments: Optional[list[Attachment]] = None,
    issuer_id: Optional[int] = None,
    user_id: Optional[int] = None,
    email_type: Optional[str] = None,
    related_object_type: Optional[str] = None,
    related_object_id: Optional[int] = None,
    subject_override: Optional[str] = None,
) -> int:
    """Send an email synchronously and log the attempt.

    Returns email_log id. Caller should typically enqueue this via the jobs
    queue instead of calling directly, except for time-critical flows
    (password reset, email verification).
    """
    # Render
    try:
        html, text = templates.render(template, context)
    except Exception as exc:
        logger.exception("Template render failed for %s", template)
        log_id = log.insert_log(
            email_type=email_type or template,
            to_email=to_email,
            to_name=to_name,
            issuer_id=issuer_id, user_id=user_id,
            related_object_type=related_object_type, related_object_id=related_object_id,
            template=template,
            payload_context=context,
            status="failed",
        )
        log.mark_failed(log_id, f"render error: {exc}")
        return log_id

    # Subject
    if subject_override:
        subject = subject_override
    else:
        subject_template = SUBJECTS_BY_TEMPLATE.get(template, "Notificación de ContaNeta")
        try:
            subject = subject_template.format(**context)
        except Exception:
            subject = subject_template

    from_email = config.get_default_from_address()
    from_name = context.get("brand_name") or config.get_default_from_name()

    # Insert log row first (queued state)
    provider = _get_provider()
    log_id = log.insert_log(
        email_type=email_type or template,
        to_email=to_email,
        to_name=to_name,
        from_email=from_email,
        from_name=from_name,
        reply_to=reply_to,
        subject=subject,
        template=template,
        provider=provider.name,
        issuer_id=issuer_id, user_id=user_id,
        related_object_type=related_object_type, related_object_id=related_object_id,
        payload_context=context,
        status="queued",
    )

    msg = EmailMessage(
        to_email=to_email,
        to_name=to_name,
        subject=subject,
        html_body=html,
        text_body=text,
        from_email=from_email,
        from_name=from_name,
        reply_to=reply_to,
        attachments=attachments or [],
        tags={"template": template, "type": email_type or template},
    )

    result = provider.send(msg)
    if result.success:
        log.mark_sent(log_id, provider_message_id=result.provider_message_id)
    else:
        log.mark_failed(log_id, result.error_message or "unknown error")

    return log_id
```

**`services/email/__init__.py`**:

```python
"""Public API for the email subsystem."""
from services.email.sender import send_email
from services.email.types import Attachment, EmailType, EmailStatus

__all__ = ["send_email", "Attachment", "EmailType", "EmailStatus"]
```

### Paso 3 — Plantillas HTML con marca intercambiable

Crear directorio `templates/emails/` con estos archivos. Todos extienden `base.html`.

**`templates/emails/base.html`**:

```html
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ subject|default('Notificación') }}</title>
<style>
  body { margin: 0; padding: 0; background: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; color: #111827; }
  .wrap { max-width: 560px; margin: 0 auto; background: #fff; padding: 32px 28px; }
  .brand { font-size: 18px; font-weight: 700; margin-bottom: 28px; color: #1f2937; }
  .brand a { color: inherit; text-decoration: none; }
  .content { font-size: 14px; line-height: 1.6; color: #374151; }
  .content p { margin: 0 0 14px; }
  .content h2 { font-size: 18px; margin: 0 0 12px; color: #111827; }
  .button { display: inline-block; padding: 10px 18px; background: #4f46e5; color: #fff !important; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; }
  .card { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin: 14px 0; font-size: 13px; }
  .footer { margin-top: 28px; padding-top: 18px; border-top: 1px solid #e5e7eb; font-size: 12px; color: #6b7280; }
  .footer a { color: #4f46e5; text-decoration: none; }
  .muted { color: #6b7280; font-size: 12px; }
</style>
</head>
<body>
  <div class="wrap">
    <div class="brand">
      {% if brand_logo_url %}
        <img src="{{ brand_logo_url }}" alt="{{ brand_name|default('ContaNeta') }}" height="32">
      {% else %}
        {{ brand_name|default('ContaNeta') }}
      {% endif %}
    </div>
    <div class="content">
      {% block email_content %}{% endblock %}
    </div>
    <div class="footer">
      <p>Este correo fue enviado por {{ brand_name|default('ContaNeta') }}.</p>
      <p class="muted">
        {% if support_email %}
          ¿Dudas? Escríbenos a <a href="mailto:{{ support_email }}">{{ support_email }}</a>.
        {% endif %}
      </p>
    </div>
  </div>
</body>
</html>
```

**`templates/emails/invoice_sent.html`**:

```html
{% extends "base.html" %}
{% block email_content %}
<h2>Recibiste una factura</h2>
<p><strong>{{ from_name }}</strong> te emitió una factura por <strong>${{ "{:,.2f}".format(total) }} {{ currency|default('MXN') }}</strong>.</p>
<div class="card">
  <p style="margin:0"><strong>Folio:</strong> {{ serie|default('') }}{{ folio|default('—') }}</p>
  <p style="margin:0"><strong>Fecha:</strong> {{ fecha_emision }}</p>
  <p style="margin:0"><strong>UUID:</strong> <span style="font-family:monospace;font-size:11px">{{ uuid }}</span></p>
</div>
<p>Adjuntos encontrarás:</p>
<ul>
  <li>📄 PDF de la factura</li>
  <li>🗂 XML del CFDI (válido para tu contabilidad)</li>
</ul>
<p>Si tienes preguntas, responde este correo y le llegará directo a {{ from_name }}.</p>
{% endblock %}
```

**`templates/emails/declaration_summary.html`**:

```html
{% extends "base.html" %}
{% block email_content %}
<h2>Tu declaración de {{ periodo }} está lista</h2>
<p>Hola {{ user_name|default('') }}, tu contador acaba de presentar tu declaración.</p>
<div class="card">
  <p style="margin:0;font-size:16px"><strong>Tipo:</strong> {{ tipo_declaracion }}</p>
  <p style="margin:8px 0 0"><strong>Resultado:</strong>
    {% if saldo_a_cargo and saldo_a_cargo > 0 %}
      Saldo a pagar <strong style="color:#dc2626">${{ "{:,.2f}".format(saldo_a_cargo) }}</strong>
    {% elif saldo_a_favor and saldo_a_favor > 0 %}
      🎉 Saldo a favor <strong style="color:#16a34a">${{ "{:,.2f}".format(saldo_a_favor) }}</strong>
    {% else %}
      Sin saldo
    {% endif %}
  </p>
  {% if linea_captura %}
    <p style="margin:8px 0 0"><strong>Línea de captura:</strong> <span style="font-family:monospace">{{ linea_captura }}</span></p>
  {% endif %}
  {% if fecha_vencimiento %}
    <p style="margin:8px 0 0"><strong>Vence:</strong> {{ fecha_vencimiento }}</p>
  {% endif %}
  {% if folio_acuse %}
    <p style="margin:8px 0 0;font-size:11px;color:#6b7280">Folio acuse SAT: {{ folio_acuse }}</p>
  {% endif %}
</div>
{% if portal_url %}
  <p><a href="{{ portal_url }}" class="button">Ver detalle en {{ brand_name|default('ContaNeta') }}</a></p>
{% endif %}
<p class="muted">Adjunto encontrarás el acuse oficial del SAT en PDF.</p>
{% endblock %}
```

**`templates/emails/welcome.html`**:

```html
{% extends "base.html" %}
{% block email_content %}
<h2>Bienvenido a {{ brand_name|default('ContaNeta') }}, {{ user_name }}</h2>
<p>Gracias por registrarte. Ya puedes empezar a emitir facturas y administrar tu contabilidad fiscal.</p>
{% if onboarding_url %}
  <p><a href="{{ onboarding_url }}" class="button">Empezar configuración</a></p>
{% endif %}
<p>Lo primero que tienes que hacer es subir tu FIEL y CSD para timbrar tus primeras facturas.</p>
{% endblock %}
```

**`templates/emails/email_verification.html`**:

```html
{% extends "base.html" %}
{% block email_content %}
<h2>Verifica tu correo</h2>
<p>Da clic en el botón para confirmar tu dirección de correo:</p>
<p><a href="{{ verification_url }}" class="button">Verificar correo</a></p>
<p class="muted">Este link expira en 24 horas. Si no fuiste tú, ignora este correo.</p>
{% endblock %}
```

**`templates/emails/password_reset.html`**:

```html
{% extends "base.html" %}
{% block email_content %}
<h2>Restablecer contraseña</h2>
<p>Recibimos una solicitud para restablecer tu contraseña.</p>
<p><a href="{{ reset_url }}" class="button">Cambiar contraseña</a></p>
<p class="muted">Este link expira en 1 hora. Si no fuiste tú, ignora este correo — tu contraseña no fue modificada.</p>
{% endblock %}
```

**`templates/emails/csd_expiring.html`**:

```html
{% extends "base.html" %}
{% block email_content %}
<h2>⚠️ Tu CSD vence pronto</h2>
<p>Tu Certificado de Sello Digital vence el <strong>{{ expires_at }}</strong> ({{ days_until_expiry }} días).</p>
<p>Para no interrumpir tu facturación:</p>
<ol>
  <li>Renueva tu CSD en el portal del SAT</li>
  <li>Sube los nuevos archivos (.cer, .key) en {{ brand_name|default('ContaNeta') }}</li>
</ol>
{% if settings_url %}
  <p><a href="{{ settings_url }}" class="button">Ir a configuración</a></p>
{% endif %}
{% endblock %}
```

**`templates/emails/fiel_expiring.html`**: idéntica estructura a `csd_expiring.html`, cambiar "CSD" por "FIEL".

**`templates/emails/trial_expiring.html`**:

```html
{% extends "base.html" %}
{% block email_content %}
<h2>Tu trial termina en {{ days_until_expiry }} día{{ 's' if days_until_expiry != 1 else '' }}</h2>
<p>Para no perder acceso a la plataforma, suscríbete antes del <strong>{{ trial_expires_at }}</strong>.</p>
{% if pricing_url %}
  <p><a href="{{ pricing_url }}" class="button">Ver planes</a></p>
{% endif %}
{% endblock %}
```

**`templates/emails/subscription_renewed.html`** y **`templates/emails/payment_failed.html`**: similares, copiar el patrón.

### Paso 4 — Job handler asíncrono

Modificar `worker.py` para registrar un handler `send_email`:

```python
# En worker.py:_load_handlers()
from services.email.sender import send_email as _send_email_sync

def handle_send_email(payload, context):
    """Job handler that calls send_email synchronously inside the worker."""
    _send_email_sync(
        to_email=payload["to_email"],
        template=payload["template"],
        context=payload.get("context", {}),
        to_name=payload.get("to_name"),
        reply_to=payload.get("reply_to"),
        issuer_id=payload.get("issuer_id"),
        user_id=payload.get("user_id"),
        email_type=payload.get("email_type"),
        related_object_type=payload.get("related_object_type"),
        related_object_id=payload.get("related_object_id"),
        # Attachments: payload uses base64-encoded content
        attachments=[
            Attachment(
                filename=a["filename"],
                content_bytes=base64.b64decode(a["content_b64"]),
                mime_type=a.get("mime_type", "application/octet-stream"),
            )
            for a in payload.get("attachments", [])
        ] if payload.get("attachments") else None,
    )

handlers["send_email"] = handle_send_email
```

Y una helper `services/email/queue.py`:

```python
"""Helper to enqueue email send jobs."""
import base64
from typing import Optional

from services.jobs import enqueue
from services.email.types import Attachment


def enqueue_send_email(
    *,
    to_email: str,
    template: str,
    context: dict,
    to_name: Optional[str] = None,
    reply_to: Optional[str] = None,
    attachments: Optional[list[Attachment]] = None,
    issuer_id: Optional[int] = None,
    user_id: Optional[int] = None,
    email_type: Optional[str] = None,
    related_object_type: Optional[str] = None,
    related_object_id: Optional[int] = None,
    dedupe_key: Optional[str] = None,
) -> int:
    """Enqueue an email send job. Returns job id."""
    payload = {
        "to_email": to_email,
        "to_name": to_name,
        "template": template,
        "context": context,
        "reply_to": reply_to,
        "issuer_id": issuer_id,
        "user_id": user_id,
        "email_type": email_type,
        "related_object_type": related_object_type,
        "related_object_id": related_object_id,
    }
    if attachments:
        payload["attachments"] = [
            {
                "filename": a.filename,
                "content_b64": base64.b64encode(a.content_bytes).decode("ascii"),
                "mime_type": a.mime_type,
            }
            for a in attachments
        ]
    return enqueue(
        job_type="send_email",
        payload=payload,
        dedupe_key=dedupe_key,
    )
```

Verificar la firma real de `services/jobs.enqueue()` antes de escribir esto. Adaptar al API real.

### Paso 5 — Webhook endpoint para Resend

Crear `routers/webhooks/__init__.py` (si no existe) y `routers/webhooks/resend.py`:

```python
"""Webhook endpoint for Resend email events."""
import hashlib
import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from services.email.config import get_resend_webhook_secret
from services.email.log import update_status_by_provider_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# Map Resend event type → (email_log.status, timestamp_field)
EVENT_MAP = {
    "email.sent":      ("sent", None),
    "email.delivered": ("delivered", "delivered_at"),
    "email.opened":    ("opened", "opened_at"),
    "email.clicked":   ("clicked", "clicked_at"),
    "email.bounced":   ("bounced", "bounced_at"),
    "email.complained":("bounced", "bounced_at"),
    "email.failed":    ("failed", None),
}


def _verify_signature(secret: str, body: bytes, signature: str) -> bool:
    """Resend uses HMAC-SHA256 over the raw body with the webhook secret."""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/resend")
async def resend_webhook(
    request: Request,
    svix_signature: str = Header(default="", alias="svix-signature"),
):
    """Receive Resend webhook events and update email_log."""
    body = await request.body()
    secret = get_resend_webhook_secret()
    if secret and not _verify_signature(secret, body, svix_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    import json
    try:
        event = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = event.get("type", "")
    data = event.get("data", {}) or {}
    provider_message_id = data.get("email_id") or data.get("id")
    if not provider_message_id:
        logger.warning("Resend webhook missing email id: %s", event_type)
        return {"ok": True, "ignored": True}

    mapping = EVENT_MAP.get(event_type)
    if not mapping:
        logger.info("Resend webhook unmapped event: %s", event_type)
        return {"ok": True, "ignored": True}

    status, ts_field = mapping
    affected = update_status_by_provider_id(provider_message_id, status, ts_field)
    return {"ok": True, "affected": affected}
```

Registrar el router en `app.py` junto a los demás:

```python
from routers.webhooks.resend import router as resend_webhook_router
app.include_router(resend_webhook_router)
```

Verificar exactamente cómo Resend firma sus webhooks (es probable que use Svix). Si el header o el algoritmo cambia, ajustar `_verify_signature`. Documentar en el log.

### Paso 6 — Configuración de entorno

Actualizar `.env.example` añadiendo:

```bash
# ── Email transactional ──────────────────────────────────
# Provider selection. "noop" = log only (dev). "resend" = real sending.
# Auto-detects to "resend" if RESEND_API_KEY is set, else "noop".
EMAIL_PROVIDER=

# Sender identity (when domain is configured)
EMAIL_FROM_NAME=ContaNeta
EMAIL_FROM_ADDRESS=noreply@contaneta.example

# Resend (https://resend.com)
RESEND_API_KEY=
RESEND_WEBHOOK_SECRET=

# Support contact shown in email footers
EMAIL_SUPPORT_ADDRESS=soporte@contaneta.example
```

Verificar en `config.py` (el general del proyecto) que estas variables se carguen y validen no-críticamente en prod (la falta de RESEND_API_KEY en prod debe ser un warning, no fatal).

### Paso 7 — Trigger points marcados (NO implementar el envío real)

Solo añadir comentarios `# TODO: enqueue_send_email(...)` en estos archivos donde corresponde, sin llamar la función. Esto es para que en un siguiente job se conecte:

1. **`routers/invoicing.py`** — después de timbrado exitoso, donde se obtiene UUID/PDF/XML:
   ```python
   # TODO: enqueue_send_email for invoice_sent if customer.email and customer.auto_send_invoices and issuer.email_notifications_enabled
   ```

2. **`routers/auth/register.py`** — después de crear el user:
   ```python
   # TODO: enqueue_send_email for welcome template
   ```

3. **`routers/auth/onboarding.py`** o donde corresponda — verificación de email:
   ```python
   # TODO: enqueue_send_email for email_verification template
   ```

4. **`routers/portal/settings.py`** o el flow de password reset (si existe):
   ```python
   # TODO: enqueue_send_email for password_reset template
   ```

5. **Crear `services/notifications/expiry_checker.py`** (nuevo archivo, no implementar la lógica completa, solo la firma):
   ```python
   """Daily check for expiring credentials (CSD, FIEL, trial)."""
   # TODO: cron job that iterates issuers and enqueues csd_expiring / fiel_expiring / trial_expiring emails
   def check_and_notify_expiring_credentials():
       pass
   ```

### Paso 8 — Tests

Crear `tests/test_email_system.py`:

```python
"""Tests for the email scaffolding (no real sending)."""
import os
from unittest.mock import patch

import pytest

from services.email.providers.noop import NoopProvider
from services.email.providers.resend import ResendProvider
from services.email.types import Attachment, EmailMessage
from services.email import config, sender, log, templates


def test_provider_defaults_to_noop_without_key(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    assert config.get_provider_name() == "noop"


def test_provider_uses_resend_when_key_set(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_xxx")
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    assert config.get_provider_name() == "resend"


def test_noop_provider_returns_success():
    p = NoopProvider()
    result = p.send(EmailMessage(to_email="a@b.com", subject="x", html_body="<p>x</p>"))
    assert result.success
    assert result.provider_message_id.startswith("noop-")


def test_template_render_welcome():
    html, text = templates.render("welcome", {"user_name": "David", "brand_name": "ContaNeta"})
    assert "David" in html
    assert "ContaNeta" in html
    assert "David" in text  # text fallback should strip HTML


def test_template_render_invoice():
    html, _ = templates.render("invoice_sent", {
        "from_name": "Ana Carolina",
        "total": 5000.0,
        "currency": "MXN",
        "serie": "A",
        "folio": "123",
        "fecha_emision": "2026-06-15",
        "uuid": "abc-123-def",
    })
    assert "Ana Carolina" in html
    assert "5,000.00" in html
    assert "A123" in html


def test_send_email_with_noop_creates_log(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    log_id = sender.send_email(
        to_email="cliente@example.com",
        template="welcome",
        context={"user_name": "Test", "brand_name": "ContaNeta"},
        email_type="welcome",
    )
    assert isinstance(log_id, int)
    # Verify the row exists and is marked sent
    from database import db_rows
    rows = db_rows("SELECT status, provider FROM email_log WHERE id = ?", (log_id,))
    assert rows and rows[0]["status"] == "sent"
    assert rows[0]["provider"] == "noop"


def test_send_email_with_failed_template_marks_failed(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    log_id = sender.send_email(
        to_email="cliente@example.com",
        template="this_template_does_not_exist",
        context={},
    )
    from database import db_rows
    rows = db_rows("SELECT status, error_message FROM email_log WHERE id = ?", (log_id,))
    assert rows[0]["status"] == "failed"
    assert "render error" in (rows[0]["error_message"] or "")


def test_email_log_webhook_status_update():
    log_id = log.insert_log(
        email_type="welcome",
        to_email="test@example.com",
        provider="resend",
    )
    log.mark_sent(log_id, provider_message_id="re_msg_123")
    affected = log.update_status_by_provider_id("re_msg_123", "delivered", "delivered_at")
    assert affected == 1
    from database import db_rows
    rows = db_rows("SELECT status, delivered_at FROM email_log WHERE id = ?", (log_id,))
    assert rows[0]["status"] == "delivered"
    assert rows[0]["delivered_at"] is not None
```

Crear `tests/test_email_webhook.py`:

```python
"""Test the Resend webhook endpoint."""
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app import app
from services.email import log


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def test_webhook_processes_delivered_event(client, monkeypatch):
    monkeypatch.delenv("RESEND_WEBHOOK_SECRET", raising=False)  # skip signature check
    log_id = log.insert_log(
        email_type="invoice_sent",
        to_email="x@x.com",
        provider="resend",
    )
    log.mark_sent(log_id, provider_message_id="re_test_abc")

    event = {
        "type": "email.delivered",
        "data": {"email_id": "re_test_abc"},
    }
    resp = client.post("/webhooks/resend", json=event)
    assert resp.status_code == 200
    assert resp.json()["affected"] == 1

    from database import db_rows
    rows = db_rows("SELECT status FROM email_log WHERE id = ?", (log_id,))
    assert rows[0]["status"] == "delivered"


def test_webhook_rejects_invalid_signature(client, monkeypatch):
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "supersecret")
    resp = client.post(
        "/webhooks/resend",
        headers={"svix-signature": "wrong"},
        json={"type": "email.sent", "data": {"email_id": "abc"}},
    )
    assert resp.status_code == 401
```

### Paso 9 — Documentación del swap

Crear `docs/email_setup.md` (o donde tengas docs):

```markdown
# Email setup

## Quick start (development)

No setup needed. By default, emails go to `noop` provider and are logged to
`email_log` table only. Run `tail -f` on logs to see what would have been sent.

## Production setup (when domain is ready)

1. Buy domain (e.g., `contaneta.com`).
2. Create Resend account at https://resend.com.
3. Add domain in Resend dashboard.
4. Add the SPF/DKIM/DMARC records Resend gives you to your DNS provider.
5. Wait for verification (~15 min).
6. Generate Resend API key.
7. Set these env vars:

   ```
   RESEND_API_KEY=re_xxx
   EMAIL_FROM_ADDRESS=facturas@contaneta.com
   EMAIL_FROM_NAME=ContaNeta
   EMAIL_SUPPORT_ADDRESS=soporte@contaneta.com
   ```

8. (Optional) Configure webhook in Resend dashboard:
   - URL: `https://yourapp.com/webhooks/resend`
   - Events: `email.delivered`, `email.opened`, `email.bounced`, `email.complained`
   - Copy webhook secret to `RESEND_WEBHOOK_SECRET`.

9. Restart app. Verify provider with: `python -c "from services.email.config import get_provider_name; print(get_provider_name())"` (should print `resend`).

10. Test with: `python -c "from services.email import send_email; send_email(to_email='tu@correo.com', template='welcome', context={'user_name': 'Test'})"`
```

---

## Acceptance criteria

- [ ] Migración 066 aplicada, idempotente
- [ ] Tabla `email_log` existe con todas las columnas listadas
- [ ] Columnas `email_notifications_enabled` (issuers) y `auto_send_invoices` (customer_profiles) existen
- [ ] `services/email/` con todos los módulos descritos
- [ ] Provider `noop` funciona y es el default sin RESEND_API_KEY
- [ ] Provider `resend` existe con HTTP client a Resend API (sin SDK)
- [ ] `templates/emails/` con todas las plantillas listadas (10 templates: base + 9)
- [ ] Handler `send_email` registrado en `worker.py`
- [ ] Helper `enqueue_send_email` funciona y usa la firma correcta de `services/jobs.enqueue`
- [ ] Webhook endpoint `/webhooks/resend` montado en app
- [ ] Variables nuevas en `.env.example`
- [ ] 5 TODO markers añadidos en los trigger points (sin lógica real)
- [ ] `tests/test_email_system.py` y `tests/test_email_webhook.py` pasan
- [ ] `.venv/bin/pytest -q` no introduce nuevas fallas (baseline = 12 pre-existentes)
- [ ] `.venv/bin/python -c "import app"` sigue limpio
- [ ] `docs/email_setup.md` describe el procedimiento de swap

## QA manual

1. `import app` limpio.
2. Importar y mandar:
   ```python
   from services.email.sender import send_email
   send_email(to_email="test@local", template="welcome", context={"user_name": "Test", "brand_name": "ContaNeta"})
   ```
   Verificar que crea row en `email_log` con `status='sent'` y `provider='noop'`.
3. Llamar al webhook con un payload de prueba y confirmar que actualiza status.
4. Arrancar el worker (`python worker.py --once`) después de encolar un email vía `enqueue_send_email` y verificar que el job se procesa.

---

## Logging requerido

Al final del job, escribir `context/implement/2026-06-15-email-system-scaffolding.md` con:

- Resumen por archivo creado/modificado
- Decisión sobre `services/email_sender.py` y `services/email_templates.py` existentes (reusados, wrappeados, reemplazados)
- Resultado de pytest (passed/failed)
- Cualquier desviación del plan y por qué
- Lista de los trigger points TODO añadidos para que se sepan ubicar en el siguiente job
- Snippet de cómo se vería el primer envío real una vez que se conecte el dominio + RESEND_API_KEY

---

## Notas para el ejecutor autónomo

- **No hagas commit** a menos que el usuario lo pida explícitamente.
- Si un módulo de la lista ya existe con otra estructura, **adáptate** sin romper. Documenta la decisión en el log.
- Si la API real de `services/jobs.enqueue()` difiere de lo asumido (firma diferente), ajusta el helper. No asumir.
- Si Resend cambió su esquema de webhook (Svix headers), seguir la doc oficial vigente — el código del job es la mejor estimación.
- Lenguaje en código: inglés. Lenguaje en plantillas/UI: español MX.
- No conectar Resend real ni configurar dominio. Eso es del siguiente job, cuando el usuario tenga el nombre y dominio.
