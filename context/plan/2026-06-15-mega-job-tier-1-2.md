# MEGA JOB — Cerrar Tier 1 + Tier 2 (excluye DIOT)

**Fecha:** 2026-06-15
**Owner:** David
**Tipo:** Multi-phase feature set (8 fases secuenciales)
**Duración estimada:** 8–14 horas autónomas
**Modo:** Autónomo extendido — el usuario estará ausente varias horas. Ejecutar las 8 fases en orden. Si una fase falla parcialmente, **documentar y seguir con la siguiente**, no abandonar el job. Al final, log consolidado.

---

## Contexto

ContaNeta tiene los cimientos listos (cancelación, tipo relación, email scaffolding). Falta cerrar el bloque que lleva al producto a estado "vendible en producción":

- Verificar lo construido en REP (no se probó con casos reales)
- Reportes mensuales/anuales nativos en portal (hoy solo via Excel manual)
- **Subir declaraciones por el contador con parser de PDF** (el diferenciador real del SaaS)
- Onboarding wizard guiado (FIEL → manifesto → CSD → primera factura)
- Polish de trial / Stripe lifecycle UX
- Validación contra Lista 69-B SAT (RFCs incumplidos)
- Audit log UI
- Reporte de cobranza PPD

**Excluido por decisión del usuario:** DIOT (Declaración Informativa de Operaciones con Terceros).

## Restricciones globales

- **Idempotencia en todo**: migraciones, jobs, scripts.
- **No breaking changes** en rutas existentes.
- **Tests verdes**: baseline 12 fallas pre-existentes (`test_facturapi_provision`, `test_fiscal_route`, `test_portal_manifesto`, `test_sat_cron_tiers`). No introducir nuevas.
- **No commits** sin permiso explícito del usuario.
- **Lenguaje código: inglés. UI: español MX.**
- **Reusar abstracciones existentes**: `services/email/`, `services/jobs.py`, `services/sat/`, helpers de portal.
- **Sleek consistent con el portal actual**: hairlines, tabular-nums, focus rings, cards redondeadas — mirar `static/css/components.css` y `templates/base_portal.html`.
- **Si una fase es bloqueada por ambigüedad**, tomar la decisión más conservadora y documentarla, **no detener el job**.

---

# FASE 1 — Verificación REP end-to-end (1–2 h)

Validar que el módulo de Complemento de Pago (`services/invoices/rep.py`) y sus rutas funcionan correctamente con casos reales y edge cases.

## Pasos

1. **Inspeccionar el módulo:** leer `services/invoices/rep.py` y `routers/portal/invoices.py` (sección registrar-pago) para entender la cobertura actual.

2. **Tests faltantes — crear `tests/test_rep_edge_cases.py`:**
   - Parcialidad #1 (primer pago): saldo_anterior = total, importe_pagado < total, saldo_insoluto = total - importe
   - Parcialidad #2+ (subsecuentes): saldo_anterior = saldo_insoluto previo, num_parcialidad correcto
   - Pago total en una parcialidad: saldo_insoluto = 0
   - USD con EquivalenciaDR: factura original USD, pago en MXN, tipo de cambio del día
   - PPD pagado en moneda distinta a la original
   - Validar que `num_parcialidad` se incrementa correctamente entre pagos
   - Validar que no se permite pagar más del saldo insoluto
   - Validar que la fecha de pago no puede ser anterior a la fecha de emisión

3. **Test de integración del flujo completo:**
   - Crear factura PPD mockeada → registrar primer pago parcial → registrar segundo pago parcial → verificar saldos en BD
   - Verificar que `invoice_payments` se llena correctamente

4. **Inspeccionar caso real:** consultar BD por facturas PPD de Diego (issuer 9), Manuel (11), Perla (9103) con saldos pendientes. Si hay, simular cálculo de qué pasaría si registráramos un pago.

5. **Si encuentras bugs**, corregirlos. Documentar en el log.

## Acceptance

- [ ] `tests/test_rep_edge_cases.py` con al menos 8 tests, todos pasan
- [ ] El flujo de 2 pagos parciales se valida en BD
- [ ] Documentado en log si hay bugs encontrados (y arreglados o no)

---

# FASE 2 — Reportes mensuales/anuales en portal (3–4 h)

Hoy el usuario depende del Excel manual. Llevar esa lógica al portal como vistas nativas con filtros y descarga.

## Pasos

### 2.1 — Migración 068 (si necesaria)

Probablemente no se necesita schema nuevo: agregamos vistas leyendo de `sat_cfdi` y `invoice_payments` directo.

### 2.2 — Servicio `services/reports/`

Crear:

```
services/reports/
├── __init__.py
├── monthly.py       # build_monthly_report(issuer_id, ym)
├── annual.py        # build_annual_report(issuer_id, year)
├── ppd_cobranza.py  # build_ppd_outstanding_report(issuer_id)
└── exporters.py     # to_excel(report) using openpyxl
```

**`monthly.py`** — usa `compute_net_totals` del módulo de tipo_relacion para garantizar consistencia. Devuelve dict con:

```python
{
  "periodo": "2026-05",
  "ingresos": {"n": int, "subtotal": float, "iva": float, "retenciones": float, "total": float},
  "gastos_brutos": {...},
  "notas_credito": {...},
  "anticipos_aplicados": {...},
  "gastos_neto": {"subtotal": float, "iva_acreditable": float, "total": float},
  "utilidad_fiscal": float,
  "iva_neto": float,  # trasladado - acreditable
  "isr_estimado": float,  # según régimen del emisor
  "cfdi_emitidos": [...],  # rows enriquecidas
  "cfdi_recibidos": [...],
}
```

**`annual.py`** — agrega los 12 meses + cálculo de ISR anual estimado por régimen:
- 626 (RESICO PF): tabla 2026
- 612 (PF Act. Empresarial): tarifa 152 con ISR
- 601 (PM): 30%

**`ppd_cobranza.py`** — facturas PPD emitidas con saldo insoluto > 0, ordenadas por antigüedad. Incluye:
- UUID, cliente, total original, saldo_insoluto, días desde emisión, # de parcialidades pagadas

### 2.3 — Rutas y templates

En `routers/portal/`:

- `GET /portal/reports/monthly?ym=YYYY-MM` → renderiza `portal_report_monthly.html`
- `GET /portal/reports/monthly/excel?ym=YYYY-MM` → descarga Excel
- `GET /portal/reports/annual?year=YYYY` → renderiza `portal_report_annual.html`
- `GET /portal/reports/annual/excel?year=YYYY` → descarga Excel
- `GET /portal/reports/ppd-cobranza` → renderiza `portal_report_ppd.html`

### 2.4 — Templates con vista visual

`templates/portal_report_monthly.html`:
- Header con periodo + selector mes
- 4 cards top: Ingresos, Gastos netos, IVA neto, ISR estimado
- 2 columnas: emitidas (con badges de tipo) y recibidas (con badges de tipo_relacion)
- Botón "Descargar Excel"
- Estilos sleek consistentes con el portal

`templates/portal_report_annual.html`:
- Header con selector año
- Tabla de 12 meses + totales
- Mini gráfico (CSS bars sin librería, ej. `<div style="height: {{ pct }}%">`)
- Cálculo de ISR anual + comparación con pagos provisionales del año

`templates/portal_report_ppd.html`:
- Lista de facturas con saldo pendiente
- Filtro por cliente
- Total pendiente arriba
- Botón "Recordar al cliente" (placeholder, no implementar envío)

### 2.5 — Link en navegación

Añadir entrada "Reportes" en la nav del portal (`templates/base_portal.html` o el componente de sidebar).

### 2.6 — Tests

`tests/test_reports.py`:
- `build_monthly_report` devuelve estructura correcta
- IVA neto coincide con `compute_net_totals`
- Excel export genera archivo válido
- Rutas responden 200 y contienen los números esperados

## Acceptance

- [ ] 3 rutas funcionando: monthly, annual, ppd-cobranza
- [ ] Excel descargable para monthly y annual
- [ ] Link "Reportes" visible en nav del portal
- [ ] Tests pasan
- [ ] ISR estimado calculado correctamente por régimen
- [ ] Visualmente consistente con el resto del portal

---

# FASE 3 — Declaration Uploader del contador con parser (4–6 h)

**El feature más estratégico del job.** El contador arrastra PDFs de acuses SAT, el sistema los lee, asigna al usuario correcto, guarda los datos fiscales y notifica al usuario.

## Pasos

### 3.1 — Migración 069

`migrations/069_declarations.sql`:

```sql
CREATE TABLE IF NOT EXISTS declarations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  uploaded_by_user_id INTEGER NOT NULL,
  tipo TEXT NOT NULL,                -- mensual_isr, mensual_iva, anual, isr_provisional, ieps_mensual, etc.
  periodo_ym TEXT,                    -- 2026-05 for mensuales
  ejercicio INTEGER,                  -- 2026 for anuales
  fecha_presentacion TEXT,
  fecha_vencimiento TEXT,
  saldo_a_cargo REAL,
  saldo_a_favor REAL,
  total_a_pagar REAL,
  linea_captura TEXT,
  folio_acuse TEXT,
  numero_operacion TEXT,
  pdf_path TEXT NOT NULL,
  pdf_sha256 TEXT NOT NULL,
  parsed_at TEXT,
  parse_confidence REAL,
  parse_engine TEXT,                  -- pdfplumber-regex, manual
  raw_extracted_json TEXT,
  status TEXT NOT NULL DEFAULT 'pending_review',  -- pending_review, validated, pagada, vencida, rejected
  user_notification_sent_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE,
  FOREIGN KEY (uploaded_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_declarations_issuer_periodo
  ON declarations(issuer_id, periodo_ym DESC);
CREATE INDEX IF NOT EXISTS idx_declarations_status
  ON declarations(status);
CREATE INDEX IF NOT EXISTS idx_declarations_uploaded_by
  ON declarations(uploaded_by_user_id, created_at DESC);

-- Track payment of each declaration
CREATE TABLE IF NOT EXISTS declaration_payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  declaration_id INTEGER NOT NULL,
  fecha_pago TEXT,
  monto REAL,
  comprobante_pago_path TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (declaration_id) REFERENCES declarations(id) ON DELETE CASCADE
);
```

### 3.2 — Servicio de parsing

Crear `services/declarations/`:

```
services/declarations/
├── __init__.py
├── parser.py          # extract_from_pdf(pdf_bytes) → dict
├── classifier.py      # classify_declaration_type(pdf_text) → tipo
├── rfc_extractor.py   # find_rfc_in_pdf(pdf_text) → str
├── storage.py         # save_pdf_for_issuer(issuer_id, pdf_bytes) → path + sha256
└── service.py         # main API: process_uploaded_pdf()
```

**`parser.py`** — usa `pdfplumber` (instalar si no está). Templates por tipo de acuse:

```python
"""Parse SAT declaration PDFs using regex on extracted text."""
import re
import logging
from typing import Optional

import pdfplumber

logger = logging.getLogger(__name__)


# Common regex patterns
RFC_PATTERN = re.compile(r'\b([A-ZÑ&]{3,4}[0-9]{6}[A-Z0-9]{3})\b')
LINEA_CAPTURA_PATTERN = re.compile(r'\b(\d{4}\s?-?\s?\d{4}\s?-?\s?\d{4}\s?-?\s?\d{4})\b')
FOLIO_ACUSE_PATTERN = re.compile(r'(?:Folio|N(?:ú|u)mero de operaci(?:ó|o)n)[:\s]+([A-Z0-9]{6,20})', re.I)
FECHA_PATTERN = re.compile(r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})')
MONTO_PATTERN = re.compile(r'\$?\s?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)')


def extract_text(pdf_bytes: bytes) -> str:
    """Extract all text from a PDF, page by page, joined."""
    import io
    text_parts = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            text_parts.append(t)
    return "\n".join(text_parts)


def extract_from_pdf(pdf_bytes: bytes) -> dict:
    """Extract fiscal fields from a SAT declaration PDF.

    Returns dict with: rfc, tipo, periodo_ym, ejercicio, fecha_presentacion,
    fecha_vencimiento, saldo_a_cargo, saldo_a_favor, total_a_pagar,
    linea_captura, folio_acuse, numero_operacion, parse_confidence (0-1).
    """
    text = extract_text(pdf_bytes)
    result = {"raw_text": text[:5000], "parse_confidence": 0.0}

    # RFC
    rfc_matches = RFC_PATTERN.findall(text)
    if rfc_matches:
        result["rfc"] = rfc_matches[0].upper()
        result["parse_confidence"] += 0.2

    # Línea de captura
    lc = LINEA_CAPTURA_PATTERN.search(text)
    if lc:
        result["linea_captura"] = re.sub(r'\s|-', '', lc.group(1))
        result["parse_confidence"] += 0.2

    # Folio acuse
    fa = FOLIO_ACUSE_PATTERN.search(text)
    if fa:
        result["folio_acuse"] = fa.group(1)
        result["parse_confidence"] += 0.15

    # Tipo de declaración (clasifica por keywords)
    result["tipo"] = _classify_tipo(text)
    if result.get("tipo"):
        result["parse_confidence"] += 0.15

    # Periodo (busca "mayo 2026", "05/2026", etc.)
    periodo = _extract_periodo(text)
    if periodo:
        result["periodo_ym"] = periodo
        result["parse_confidence"] += 0.1

    # Saldos
    saldo_cargo = _extract_amount_near(text, [
        r'(?:Cantidad|Total)\s*a\s*(?:cargo|pagar)',
        r'Importe a pagar',
    ])
    if saldo_cargo is not None:
        result["saldo_a_cargo"] = saldo_cargo
        result["total_a_pagar"] = saldo_cargo
        result["parse_confidence"] += 0.1

    saldo_favor = _extract_amount_near(text, [
        r'Saldo a favor', r'Cantidad a favor',
    ])
    if saldo_favor is not None:
        result["saldo_a_favor"] = saldo_favor
        result["parse_confidence"] += 0.05

    # Fechas
    fechas = _extract_dates(text)
    if "fecha_presentacion" in fechas:
        result["fecha_presentacion"] = fechas["fecha_presentacion"]
        result["parse_confidence"] += 0.05
    if "fecha_vencimiento" in fechas:
        result["fecha_vencimiento"] = fechas["fecha_vencimiento"]
        result["parse_confidence"] += 0.05

    result["parse_confidence"] = min(1.0, result["parse_confidence"])
    return result


def _classify_tipo(text: str) -> Optional[str]:
    t = text.lower()
    if "isr" in t and ("provisional" in t or "mensual" in t):
        return "mensual_isr"
    if "iva" in t and ("definitivo" in t or "mensual" in t):
        return "mensual_iva"
    if "ieps" in t and "mensual" in t:
        return "mensual_ieps"
    if "anual" in t and "isr" in t:
        return "anual_isr"
    if "pago referenciado" in t or "captura de pago" in t:
        return "pago_referenciado"
    if "informativa" in t:
        return "informativa"
    return None


def _extract_periodo(text: str) -> Optional[str]:
    """Extract periodo as YYYY-MM."""
    MONTHS = {
        "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
        "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
        "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
    }
    m = re.search(r'(?:periodo|mes(?:\s+a\s+declarar)?)\s*:?\s*(\w+)\s+(?:de\s+)?(\d{4})', text, re.I)
    if m:
        month_name = m.group(1).lower()
        year = m.group(2)
        if month_name in MONTHS:
            return f"{year}-{MONTHS[month_name]}"
    m = re.search(r'(\d{2})[/\-](\d{4})', text)
    if m:
        return f"{m.group(2)}-{m.group(1)}"
    return None


def _extract_amount_near(text: str, label_patterns: list[str]) -> Optional[float]:
    for label_pat in label_patterns:
        match = re.search(label_pat + r'[\s:$]*' + MONTO_PATTERN.pattern, text, re.I)
        if match:
            amt = match.group(1) if match.lastindex else None
            if amt:
                try:
                    return float(amt.replace(",", ""))
                except ValueError:
                    continue
    return None


def _extract_dates(text: str) -> dict:
    result = {}
    fp = re.search(r'Fecha\s+(?:de\s+)?presentaci(?:ó|o)n[:\s]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})', text, re.I)
    if fp:
        result["fecha_presentacion"] = _normalize_date(fp.group(1))
    fv = re.search(r'Fecha\s+(?:l(?:í|i)mite\s+de\s+pago|vencimiento)[:\s]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})', text, re.I)
    if fv:
        result["fecha_vencimiento"] = _normalize_date(fv.group(1))
    return result


def _normalize_date(s: str) -> str:
    parts = re.split(r'[/\-]', s)
    if len(parts) == 3:
        d, m, y = parts
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    return s
```

**`rfc_extractor.py`** — separado para clarity:

```python
"""Find the taxpayer's RFC inside a parsed declaration PDF."""
import re

RFC_RE = re.compile(r'\b([A-ZÑ&]{3,4}[0-9]{6}[A-Z0-9]{3})\b')


def find_rfc_in_pdf(text: str) -> str | None:
    """Returns the most likely RFC of the taxpayer (not the SAT signing RFC).

    Strategy: look for RFC near labels "RFC", "Contribuyente", "Razón social".
    Filter out the SAT institutional RFCs (SAT970701NN3 and similar).
    """
    SAT_RFCS = {"SAT970701NN3"}
    candidates = []
    # Pattern: RFC label + value within 80 chars
    label_re = re.compile(r'(RFC|Contribuyente)\s*:?\s*([A-ZÑ&]{3,4}[0-9]{6}[A-Z0-9]{3})', re.I)
    for m in label_re.finditer(text):
        rfc = m.group(2).upper()
        if rfc not in SAT_RFCS:
            candidates.append(rfc)
    if candidates:
        return candidates[0]
    # Fallback: any RFC found, excluding SAT
    all_rfcs = [r.upper() for r in RFC_RE.findall(text) if r.upper() not in SAT_RFCS]
    return all_rfcs[0] if all_rfcs else None
```

**`storage.py`**:

```python
"""Storage for declaration PDFs — tenant-scoped paths with SHA-256."""
import hashlib
import os
from pathlib import Path
from typing import Tuple


BASE_DIR = Path(os.getenv("DECLARATION_STORAGE_DIR", "./storage/declarations"))


def save_pdf_for_issuer(issuer_id: int, pdf_bytes: bytes, periodo_ym: str | None) -> Tuple[str, str]:
    """Save PDF under storage/declarations/{issuer_id}/{YYYY-MM}/{sha256}.pdf
    Returns (relative_path, sha256_hex).
    """
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    subdir = BASE_DIR / str(issuer_id) / (periodo_ym or "unsorted")
    subdir.mkdir(parents=True, exist_ok=True)
    path = subdir / f"{sha[:16]}.pdf"
    if not path.exists():
        path.write_bytes(pdf_bytes)
    rel = str(path.relative_to(BASE_DIR.parent.parent) if BASE_DIR.is_absolute() else path)
    return rel, sha
```

**`service.py`**:

```python
"""Top-level API for declaration upload + processing."""
import logging
from typing import Optional

from database import db
from services.declarations import parser, rfc_extractor, storage

logger = logging.getLogger(__name__)


def process_uploaded_pdf(
    *,
    pdf_bytes: bytes,
    uploaded_by_user_id: int,
    filename: str,
    target_issuer_id: Optional[int] = None,
) -> dict:
    """Parse a single PDF and persist the declaration row.

    If target_issuer_id is provided, use it directly.
    Otherwise, try to auto-detect from the RFC inside the PDF.

    Returns dict with declaration_id, status, parse_confidence, matched_issuer_id.
    """
    extracted = parser.extract_from_pdf(pdf_bytes)
    rfc_in_pdf = rfc_extractor.find_rfc_in_pdf(extracted.get("raw_text", ""))

    issuer_id = target_issuer_id
    if not issuer_id and rfc_in_pdf:
        conn = db()
        row = conn.execute(
            "SELECT id FROM issuers WHERE UPPER(rfc) = UPPER(?) AND active = 1 LIMIT 1",
            (rfc_in_pdf,),
        ).fetchone()
        conn.close()
        if row:
            issuer_id = row[0] if not isinstance(row, dict) else row["id"]

    if not issuer_id:
        return {
            "status": "rejected",
            "reason": "no_matching_issuer",
            "rfc_in_pdf": rfc_in_pdf,
            "parse_confidence": extracted.get("parse_confidence", 0),
        }

    rel_path, sha = storage.save_pdf_for_issuer(
        issuer_id, pdf_bytes, extracted.get("periodo_ym")
    )

    # Check duplicate by SHA
    conn = db()
    dup = conn.execute(
        "SELECT id FROM declarations WHERE pdf_sha256 = ? LIMIT 1", (sha,),
    ).fetchone()
    if dup:
        conn.close()
        return {
            "status": "duplicate",
            "declaration_id": dup[0] if not isinstance(dup, dict) else dup["id"],
            "reason": "Same PDF already uploaded",
        }

    cur = conn.execute(
        """INSERT INTO declarations (
            issuer_id, uploaded_by_user_id, tipo, periodo_ym, fecha_presentacion,
            fecha_vencimiento, saldo_a_cargo, saldo_a_favor, total_a_pagar,
            linea_captura, folio_acuse, pdf_path, pdf_sha256,
            parsed_at, parse_confidence, parse_engine, raw_extracted_json, status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, datetime('now'), ?, 'pdfplumber-regex', ?, ?)""",
        (
            issuer_id, uploaded_by_user_id,
            extracted.get("tipo") or "desconocido",
            extracted.get("periodo_ym"),
            extracted.get("fecha_presentacion"),
            extracted.get("fecha_vencimiento"),
            extracted.get("saldo_a_cargo"),
            extracted.get("saldo_a_favor"),
            extracted.get("total_a_pagar"),
            extracted.get("linea_captura"),
            extracted.get("folio_acuse"),
            rel_path, sha,
            extracted.get("parse_confidence", 0),
            __import__("json").dumps(extracted, default=str),
            "pending_review" if extracted.get("parse_confidence", 0) < 0.7 else "validated",
        ),
    )
    declaration_id = cur.lastrowid
    conn.commit()
    conn.close()

    return {
        "status": "saved",
        "declaration_id": declaration_id,
        "matched_issuer_id": issuer_id,
        "rfc_in_pdf": rfc_in_pdf,
        "parse_confidence": extracted.get("parse_confidence", 0),
        "needs_review": extracted.get("parse_confidence", 0) < 0.7,
    }
```

### 3.3 — Rutas y UI

En `routers/portal/`:

- `GET /portal/contador/declaraciones` — landing del contador, lista de declaraciones recientes
- `POST /portal/contador/declaraciones/upload` — recibe multi-PDF, procesa, devuelve JSON con resultados
- `GET /portal/contador/declaraciones/{id}/review` — vista para validar manualmente cuando confidence < 0.7
- `POST /portal/contador/declaraciones/{id}/validate` — confirmar/corregir y mandar email al usuario
- `GET /portal/declaraciones` — vista para el usuario final con sus declaraciones
- `GET /portal/declaraciones/{id}` — detalle + descargar PDF

### 3.4 — Templates

`templates/contador_declaraciones.html`:
- Zona drag-and-drop para PDFs (UI sleek)
- Tabla de últimas declaraciones procesadas con estado: ✓ validado / ⚠ revisar / ✗ rechazado
- Filtros por contribuyente, periodo, estado

`templates/contador_declaraciones_review.html`:
- Vista lado a lado: PDF embed + formulario con campos extraídos
- Botones "Confirmar y notificar" y "Asignar a otro contribuyente"

`templates/portal_declaraciones.html`:
- Vista del usuario final con cards mensuales (badges: Pagada / Pendiente / Vencida)
- Click → detalle + link a pagar (link al banco/SAT, no integración real)

### 3.5 — Notificación email al usuario

Cuando el contador valide una declaración → encolar email usando el sistema existente:

```python
from services.email.queue import enqueue_send_email

enqueue_send_email(
    to_email=user_email,
    template="declaration_summary",
    context={
        "user_name": user_name,
        "periodo": declaration.periodo_ym,
        "tipo_declaracion": declaration.tipo,
        "saldo_a_cargo": declaration.saldo_a_cargo,
        "saldo_a_favor": declaration.saldo_a_favor,
        "linea_captura": declaration.linea_captura,
        "fecha_vencimiento": declaration.fecha_vencimiento,
        "folio_acuse": declaration.folio_acuse,
        "portal_url": f"/portal/declaraciones/{declaration.id}",
        "brand_name": "ContaNeta",
    },
    email_type="declaration_summary",
    issuer_id=declaration.issuer_id,
    related_object_type="declaration",
    related_object_id=declaration.id,
)
```

### 3.6 — Tests

`tests/test_declaration_parser.py`:
- Test con un fixture PDF de acuse mensual ISR (crear PDF mock con `reportlab` si no hay sample real)
- Test de extracción de RFC, línea captura, montos
- Test de `process_uploaded_pdf` con auto-routing por RFC
- Test de detección de duplicados por SHA
- Test de rechazo cuando no hay RFC match

## Acceptance

- [ ] Migración 069 aplicada
- [ ] `services/declarations/` con todos los módulos
- [ ] 4 rutas para contador, 2 rutas para usuario final
- [ ] Templates sleek funcionando
- [ ] Auto-routing por RFC funciona en al menos 1 sample
- [ ] Notificación email se encola al validar
- [ ] Tests pasan
- [ ] Si pdfplumber no está instalado, agregarlo a `requirements.txt`

---

# FASE 4 — Onboarding Wizard (2–3 h)

Guiar al nuevo usuario paso a paso desde registro hasta emisión de primera factura.

## Pasos

### 4.1 — Diseño del flow

5 pasos visibles arriba como progress bar:

1. **Perfil** — nombre, RFC, régimen
2. **FIEL** — subir .cer .key + password
3. **Manifesto** — firmar carta manifesto (iframe Facturapi)
4. **CSD** — subir certificado de sello digital
5. **Primera factura** — link al form de creación

### 4.2 — Ruta y estado

Crear `routers/portal/onboarding_wizard.py` o ampliar el existente. Track del step actual en `issuers.onboarding_step` (nueva columna).

### 4.3 — Migración 070

```sql
ALTER TABLE issuers ADD COLUMN onboarding_step INTEGER NOT NULL DEFAULT 0;
ALTER TABLE issuers ADD COLUMN onboarding_dismissed INTEGER NOT NULL DEFAULT 0;
```

### 4.4 — Template `templates/onboarding_wizard.html`

Wizard sleek:
- Progress bar arriba con 5 dots
- Cada step en su propia card animada
- Botón "Continuar" deshabilitado hasta que el step esté completo
- Botón "Saltar por ahora" para que no sea bloqueante
- Cuando completa el último step: confeti CSS + redirect a dashboard con toast de bienvenida

### 4.5 — Redirect inteligente

En `routers/portal/dashboard.py` o el middleware: si `onboarding_step < 5` y `onboarding_dismissed = 0`, mostrar banner persistente "Tu cuenta está incompleta — continúa el onboarding" con CTA. No forzar redirect.

### 4.6 — Tests

`tests/test_onboarding_wizard.py`:
- Visitar `/portal/onboarding` con cuenta nueva → step 1
- Completar perfil → step 2
- Mock FIEL upload → step 3
- ...
- Skip funciona

## Acceptance

- [ ] Migración 070 aplicada
- [ ] Wizard responde en `/portal/onboarding`
- [ ] 5 steps con UI sleek
- [ ] Skip funcional
- [ ] Banner en dashboard cuando onboarding incompleto
- [ ] Tests pasan

---

# FASE 5 — Trial / Stripe lifecycle UX (2–3 h)

Mejorar la visibilidad y experiencia de límites de plan, expiración de trial, fallos de pago.

## Pasos

### 5.1 — Banner de trial restante

En `templates/base_portal.html` (o componente top): si `issuer.plan == 'free'` o trial activo, mostrar:

- Si quedan > 7 días: "Tu trial termina el DD/MMM" (gris)
- Si quedan 1-7 días: amarillo
- Si vencido: rojo + CTA "Suscribirse ahora"

### 5.2 — Banner de límites

Calcular en cada request: `current_usage` (facturas timbradas este mes) y `plan_limit`.

- Si >= 80%: banner amarillo "Has usado X de Y facturas este mes"
- Si >= 100%: banner rojo + bloqueo del botón "Nueva factura"

### 5.3 — Página de billing

`templates/portal_billing.html`:
- Plan actual, fecha de renovación
- Botón "Cambiar plan" → modal con opciones
- Botón "Cancelar suscripción" → flujo de confirmación con feedback opcional
- Historial de pagos
- "Actualizar método de pago" → redirect a Stripe Customer Portal

### 5.4 — Webhooks Stripe — verificar

Inspeccionar `routers/billing.py` y verificar que se manejan:
- `customer.subscription.created/updated/deleted`
- `invoice.paid`
- `invoice.payment_failed` → enviar email al usuario via el sistema de email scaffolding (template `payment_failed`)
- `customer.subscription.trial_will_end` → encolar email `trial_expiring`

Si algún webhook no está, agregarlo.

### 5.5 — Cron / job de aviso de trial

`services/notifications/trial_checker.py`:

```python
def check_and_notify_trial_expiring():
    """Run daily: notify users whose trial expires in 7, 3, or 1 day."""
    # Query issuers with trial_expires_at within those windows
    # Enqueue trial_expiring email
```

Registrar en worker.

### 5.6 — Tests

`tests/test_billing_lifecycle.py`:
- Banner de trial aparece correctamente según días restantes
- Bloqueo en plan limit
- Webhook payment_failed dispara email
- Cron de trial expiring encola correctamente

## Acceptance

- [ ] Banner de trial en todas las páginas del portal
- [ ] Banner de uso de plan (80% / 100%)
- [ ] `/portal/billing` muestra plan + historial + acciones
- [ ] Webhooks Stripe manejan los 5 eventos principales
- [ ] Cron de trial expiring registrado
- [ ] Tests pasan

---

# FASE 6 — Validación contra Lista 69-B SAT (1–2 h)

Bloquear / advertir emisión a RFCs de contribuyentes en la lista de empresas que facturan operaciones simuladas (EFOS).

## Pasos

### 6.1 — Servicio de descarga

`services/sat/lista_69b.py`:

```python
"""Download and parse the SAT public list of contribuyentes 69-B (EFOS)."""
import csv
import io
import logging
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

# URL pública del SAT (verificar URL vigente en 2026)
LISTA_URL = "http://omawww.sat.gob.mx/cifras_sat/Documents/Listado_Completo_69-B.csv"


def fetch_lista() -> list[dict]:
    """Returns list of dicts with: rfc, nombre, situacion."""
    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            resp = client.get(LISTA_URL)
        if resp.status_code != 200:
            raise RuntimeError(f"SAT returned {resp.status_code}")
        # Parse CSV
        text = resp.text
        reader = csv.DictReader(io.StringIO(text))
        return [{"rfc": r.get("RFC", "").upper(), "nombre": r.get("Nombre del Contribuyente", ""),
                 "situacion": r.get("Supuesto", "")} for r in reader]
    except Exception as exc:
        logger.warning("69-B fetch failed: %s", exc)
        return []
```

### 6.2 — Migración 071

```sql
CREATE TABLE IF NOT EXISTS sat_lista_69b (
  rfc TEXT PRIMARY KEY,
  nombre TEXT,
  situacion TEXT,             -- Definitivo, Presunto, Desvirtuado, etc.
  refreshed_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### 6.3 — Job de refresco semanal

`worker.py` handler `refresh_lista_69b` que descarga, parsea y upserts. Encolar manualmente la primera vez para llenar BD.

### 6.4 — Validación al timbrar

En `routers/invoicing.py:_submit_impl`, antes de timbrar, validar contra `sat_lista_69b`:

```python
conn = db()
row = conn.execute(
    "SELECT situacion FROM sat_lista_69b WHERE rfc = ? LIMIT 1",
    (customer_rfc.upper(),),
).fetchone()
conn.close()
if row:
    sit = (row["situacion"] if not isinstance(row, tuple) else row[0]) or ""
    if sit.lower() in ("definitivo", "sentencia favorable"):
        # Block emission
        raise ValueError(
            f"El RFC {customer_rfc} está en la Lista 69-B del SAT como '{sit}'. "
            "No se puede emitir CFDI a este receptor."
        )
    if sit.lower() == "presunto":
        # Warn but allow (could be appealed)
        logger.warning("Emisión a RFC en 69-B presunto: %s", customer_rfc)
```

### 6.5 — UI: badge en customer_profiles

En el listado de clientes, mostrar badge rojo "69-B" si está en la lista. En el form de creación, validar en blur de RFC.

### 6.6 — Tests

`tests/test_lista_69b.py`:
- Inserta RFC fake en `sat_lista_69b` → intentar emitir → debe bloquear
- RFC no en lista → emite normal
- Mock del fetch

## Acceptance

- [ ] Migración 071 aplicada
- [ ] Servicio fetch funciona (o falla silenciosamente si URL cambió)
- [ ] Validación bloquea emisión a RFCs definitivos
- [ ] Badge "69-B" en UI
- [ ] Tests pasan

---

# FASE 7 — Audit log UI (1 h)

Exponer el `action_log` existente como vista en el portal.

## Pasos

### 7.1 — Ruta y template

`GET /portal/audit-log` → lista paginada con filtros (acción, usuario, fecha)

`templates/portal_audit_log.html`:
- Tabla con icono por tipo de acción
- Filtros chips: Login, Factura emitida, Factura cancelada, Cambio de FIEL, etc.
- Date range picker
- Export CSV

### 7.2 — Solo para owners/admins

Verificar role en `get_portal_issuer`. Si no es owner/admin → redirect.

## Acceptance

- [ ] Ruta funcional con paginación
- [ ] Solo accesible para owner/admin
- [ ] Export CSV funciona

---

# FASE 8 — Constancia Situación Fiscal upload + parser básico (1–2 h)

Simplificado: NO autodescarga, sí parse. Usuario sube su constancia, sistema extrae datos para validar contra lo registrado.

## Pasos

### 8.1 — Migración 072

```sql
ALTER TABLE issuers ADD COLUMN constancia_pdf_path TEXT;
ALTER TABLE issuers ADD COLUMN constancia_uploaded_at TEXT;
ALTER TABLE issuers ADD COLUMN constancia_extracted_json TEXT;
```

### 8.2 — Servicio

`services/constancia/parser.py` — similar a declarations parser, extrae:
- RFC, CURP (si PF)
- Razón social
- Régimen fiscal
- Código postal
- Domicilio
- Obligaciones fiscales

### 8.3 — Ruta + UI

- `POST /portal/settings/constancia/upload` — drag&drop, parsea, compara contra `issuers` actual
- Si difiere → mostrar diff y permitir actualizar
- Si coincide → confirmar como "Datos verificados"

### 8.4 — Badge "Verificado"

En `portal_settings.html`, si `constancia_uploaded_at` existe y los datos coinciden → mostrar "✓ Datos fiscales verificados".

## Acceptance

- [ ] Migración 072 aplicada
- [ ] Upload + parse funciona
- [ ] Diff con datos actuales se muestra
- [ ] Badge "Verificado" en settings

---

## Logging consolidado al final

Cuando todas las fases terminen (o fallen documentadas), escribir `context/implement/2026-06-15-mega-job-tier-1-2.md` con:

- Tabla resumen: Fase | Estado (✅ / ⚠ parcial / ✗ falló) | Archivos | Tests
- Por cada fase: archivos modificados, decisiones, desviaciones, bugs encontrados
- Resultado pytest final (passed/failed)
- Estado del baseline (las 12 fallas pre-existentes)
- Migrations aplicadas
- Lista de TODOs nuevos que quedaron pendientes
- Sugerencia de orden para validación manual cuando el usuario regrese

---

## Notas críticas para el ejecutor autónomo

- **El usuario estará ausente varias horas**. Tomar decisiones razonables sin pedir input.
- **Si una librería no está instalada** (pdfplumber, reportlab para mock PDFs), agregarla a `requirements.txt` e instalar.
- **Si una API externa (SAT 69-B URL) falla**, dejar la infraestructura pero documentar la falla en el log. No abortar.
- **Si una fase resulta más compleja que estimada**, hacer una versión MVP que cumpla acceptance mínima y documentar lo que se simplificó.
- **NO HACER COMMITS** — el usuario verá los cambios y decidirá.
- **Mantener tests pasando**: si algo introduces rompe tests existentes, arréglalo o revierte el cambio antes de pasar a la siguiente fase.
- **Reusar `compute_net_totals`** del módulo de tipo_relacion en reportes para garantizar consistencia con el portal.
- **Reusar el sistema de email** (`services/email/queue.py:enqueue_send_email`) para todas las notificaciones nuevas — está en modo noop, perfecto para dev.
- **Reusar `services/jobs.py`** para todos los crons (refresh 69-B, trial checker, declaration notification).
- **Sleek design consistente**: ver `templates/base_portal.html` y `static/css/portal.css` para tokens (--accent, --border, --surface-2, hairlines).

## Orden recomendado de ejecución

Fases independientes pueden hacerse en cualquier orden. Sugerencia:

1. Fase 1 (REP verificación) — corta, valida lo existente
2. Fase 2 (Reportes) — base para muchas otras
3. Fase 3 (Declaration uploader) — la más larga y estratégica
4. Fase 4 (Onboarding wizard)
5. Fase 5 (Trial/Stripe UX)
6. Fase 6 (Lista 69-B)
7. Fase 7 (Audit log UI)
8. Fase 8 (Constancia)
