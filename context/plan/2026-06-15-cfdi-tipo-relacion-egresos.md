# Job: CFDI TipoRelacion para Egresos — clasificación y cálculo neto correcto

**Fecha:** 2026-06-15
**Owner:** David
**Tipo:** Feature (CFDI 4.0 + UX/contabilidad)
**Duración estimada:** 1–1.5 días autónomos
**Modo:** Autónomo — ejecutar de corrido sin pausas. Si encuentras un bloqueador, documéntalo en el log y sigue con el siguiente paso.

---

## Contexto / Problema

Hoy `sat_cfdi.tipo_comprobante` distingue I/E/P/N/T, pero cuando es **E (Egreso)** todas las facturas se ven igual en la UI y se restan ciegamente del total mensual. Eso confunde al usuario y al contador porque dentro del tipo E hay subtipos contablemente muy distintos:

- **TipoRelacion 01** = Nota de crédito por descuento/bonificación → **sí reduce gasto real**
- **TipoRelacion 03** = Devolución de mercancía → **sí reduce gasto real**
- **TipoRelacion 04** = Sustitución de CFDI cancelado → **no afecta totales (reemplazo)**
- **TipoRelacion 07** = **Aplicación de anticipo** → **resta porque el gasto ya se dedujo cuando se pagó el anticipo en otro mes**

Caso real validado: Manuel Montoya (issuer_id=11) recibió en mayo 2026 dos facturas de MULTI CASSETTE el mismo día por el mismo monto ($83,113): folio 2784 tipo I (DANGEROUS 2 BUS+) y folio 2785 tipo E (Aplicación de anticipo). El anticipo se había facturado en feb-2026 (folio 2661). En mayo el neto fiscal es $0, lo cual es correcto, pero hoy la UI no explica nada.

El SAT expone esta información en el nodo `cfdi:CfdiRelacionados` del XML, con atributo `TipoRelacion` y uno o más `cfdi:CfdiRelacionado UUID="..."`.

## Objetivo

Capturar `TipoRelacion` y los UUIDs relacionados, surface in UI con label humano + signo claro, y recalcular el neto mensual considerando la semántica de cada tipo de Egreso.

## Restricciones

- **No cambiar URLs ni breaking changes**: rutas existentes responden igual.
- **Migración idempotente** con `ADD COLUMN IF NOT EXISTS`.
- **Backfill no-fatal**: si un XML no parsea, log warning y seguir.
- **Tests verdes antes y después**: `.venv/bin/pytest -q` debe quedar igual o mejor que la baseline (12 fallas pre-existentes documentadas: `test_facturapi_provision`, `test_fiscal_route`, `test_portal_manifesto`, `test_sat_cron_tiers`).
- **No tocar facturas tipo I, P, N, T**: el cambio solo aplica a Egresos.

---

## Plan de implementación (en orden)

### Paso 1 — Migración 065

Archivo: `migrations/065_cfdi_tipo_relacion.sql`

```sql
-- Migration 065: add CFDI TipoRelacion + related UUIDs to sat_cfdi
-- Allows distinguishing nota de crédito vs aplicación de anticipo vs sustitución
-- for proper monthly net calculation per SAT prellenado semantics.

ALTER TABLE sat_cfdi ADD COLUMN tipo_relacion TEXT;
ALTER TABLE sat_cfdi ADD COLUMN related_uuids TEXT; -- JSON array of UUID strings

CREATE INDEX IF NOT EXISTS idx_sat_cfdi_tipo_relacion
  ON sat_cfdi(issuer_id, tipo_comprobante, tipo_relacion);
```

`migrations_runner.py` aplica idempotente al startup. **Verificar** que `IF NOT EXISTS` esté soportado en `ADD COLUMN` (SQLite 3.35+); si no, envolver en try/except con `PRAGMA table_info`.

### Paso 2 — Parser XML actualizado

Localizar el módulo que parsea XML de CFDI recibidos (probablemente `services/sat/sat_full_sync.py` o `services/sat/sat_metadata_only_repair.py`). Buscar dónde se llena `sat_cfdi` desde el XML.

Añadir extracción de:

```python
# CfdiRelacionados node (CFDI 4.0)
ns = {'cfdi': 'http://www.sat.gob.mx/cfd/4'}
rel_node = root.find('cfdi:CfdiRelacionados', ns)
tipo_relacion = None
related_uuids = []
if rel_node is not None:
    tipo_relacion = rel_node.get('TipoRelacion')
    for r in rel_node.findall('cfdi:CfdiRelacionado', ns):
        u = r.get('UUID')
        if u:
            related_uuids.append(u.lower())
```

Guardar `tipo_relacion` y `json.dumps(related_uuids) if related_uuids else None`.

**Importante**: el XSD permite namespace `cfd:` también en algunos XMLs viejos. Probar ambos prefijos.

### Paso 3 — Backfill de Egresos existentes

Script: `scripts/backfill_tipo_relacion.py`

Procesa todos los Egresos (`direction='received' AND tipo_comprobante='E'`) que tienen `xml_path` no nulo y `tipo_relacion IS NULL`. Lee el XML, extrae y actualiza. Idempotente, ejecutable múltiples veces.

```python
"""Backfill tipo_relacion + related_uuids on existing Egreso CFDI."""
import json
import logging
from pathlib import Path
from xml.etree import ElementTree as ET
from database import db

logger = logging.getLogger(__name__)
NS = {'cfdi': 'http://www.sat.gob.mx/cfd/4', 'cfd': 'http://www.sat.gob.mx/cfd/4'}

def extract(xml_path: Path) -> tuple[str | None, list[str]]:
    tree = ET.parse(str(xml_path))
    root = tree.getroot()
    for prefix in ('cfdi', 'cfd'):
        rel = root.find(f'{{{NS[prefix]}}}CfdiRelacionados')
        if rel is not None:
            tipo = rel.get('TipoRelacion')
            uuids = [r.get('UUID', '').lower() for r in rel if r.get('UUID')]
            return tipo, uuids
    return None, []

def main():
    conn = db()
    rows = conn.execute(
        """SELECT id, xml_path FROM sat_cfdi
           WHERE tipo_comprobante = 'E'
             AND direction = 'received'
             AND tipo_relacion IS NULL
             AND xml_path IS NOT NULL""").fetchall()
    n_ok = n_err = n_skip = 0
    for r in rows:
        p = Path(r['xml_path'])
        if not p.exists():
            n_skip += 1
            continue
        try:
            tipo, uuids = extract(p)
            conn.execute(
                "UPDATE sat_cfdi SET tipo_relacion = ?, related_uuids = ? WHERE id = ?",
                (tipo, json.dumps(uuids) if uuids else None, r['id']),
            )
            n_ok += 1
        except Exception as e:
            logger.warning("backfill failed id=%s: %s", r['id'], e)
            n_err += 1
    conn.commit()
    conn.close()
    print(f"OK: {n_ok}  errors: {n_err}  missing-xml: {n_skip}")

if __name__ == "__main__":
    main()
```

Ejecutar al final con `.venv/bin/python scripts/backfill_tipo_relacion.py` y confirmar números.

### Paso 4 — Mapeo código → label humano

Archivo: `services/sat/cfdi_relacion_labels.py` (nuevo)

```python
"""Human-readable labels and accounting semantics for CFDI TipoRelacion."""

# c_TipoRelacion catalog (SAT)
TIPO_RELACION_LABELS = {
    "01": "Nota de crédito",
    "02": "Nota de débito",
    "03": "Devolución",
    "04": "Sustitución",
    "05": "Traslado",
    "06": "Traslado previo",
    "07": "Anticipo aplicado",
    "08": "Operación CFDI Régimen 23",
    "09": "Factura por traslados",
}

# Which TipoRelacion subtracts from monthly net (gasto deducible)
# 01/03 = real reduction (refund); 07 = already deducted in prior month (anticipo)
SUBTRACTS_FROM_TOTAL = {"01", "03", "07"}

# Which is informational only (no impact on totals)
NEUTRAL = {"04", "05", "06"}


def label_for_received(tipo_comprobante: str, tipo_relacion: str | None) -> str:
    """Return the human label for a received CFDI row in the UI."""
    tc = (tipo_comprobante or "").upper()
    if tc == "I":
        return "Ingreso"
    if tc == "N":
        return "Nómina"
    if tc == "P":
        return "Pago (REP)"
    if tc == "T":
        return "Traslado"
    if tc == "E":
        return TIPO_RELACION_LABELS.get(tipo_relacion or "", "Egreso")
    return tipo_comprobante or "—"


def signed_amount(total: float, tipo_comprobante: str, tipo_relacion: str | None) -> float:
    """Return total with the sign that should be applied to monthly net.

    Positive = sums to gastos del mes.
    Negative = subtracts from gastos del mes (NC reales, anticipos aplicados).
    Zero = neutral (sustitución, traslados, pagos).
    """
    tc = (tipo_comprobante or "").upper()
    tr = tipo_relacion or ""
    if tc == "P":  # pagos no afectan
        return 0.0
    if tc == "E":
        if tr in SUBTRACTS_FROM_TOTAL:
            return -abs(total)
        if tr in NEUTRAL:
            return 0.0
        # Default: unknown E type → treat as NC (conservative)
        return -abs(total)
    return abs(total)  # I, N suman


def signed_multiplier(tipo_comprobante: str, tipo_relacion: str | None) -> int:
    """Return +1 / -1 / 0 to apply to ALL fiscal fields of the CFDI.

    Use this to compute net subtotal, net IVA, net retenciones, net total
    consistently — same sign for every field of the row.
    """
    tc = (tipo_comprobante or "").upper()
    tr = tipo_relacion or ""
    if tc == "P":
        return 0
    if tc == "E":
        if tr in SUBTRACTS_FROM_TOTAL:
            return -1
        if tr in NEUTRAL:
            return 0
        return -1  # conservative default
    return 1  # I, N, T


def compute_net_totals(rows: list) -> dict:
    """Aggregate received CFDI into net subtotal, IVA, retenciones, total.

    Each row should expose: tipo_comprobante, tipo_relacion, subtotal, impuestos
    (IVA trasladado), retenciones, total. IVA from notas/anticipos is subtracted
    from IVA acreditable so the user sees the real deductible amounts that
    match SAT's prellenado.
    """
    net = {
        "subtotal": 0.0, "iva": 0.0, "retenciones": 0.0, "total": 0.0,
        # Breakdown for the resumen card
        "ingresos_n": 0, "ingresos_sub": 0.0, "ingresos_iva": 0.0, "ingresos_total": 0.0,
        "notas_n": 0,    "notas_sub": 0.0,    "notas_iva": 0.0,    "notas_total": 0.0,
        "anticipos_n": 0,"anticipos_sub": 0.0,"anticipos_iva": 0.0,"anticipos_total": 0.0,
    }
    for r in rows:
        tc = (r.get("tipo_comprobante") or "").upper()
        tr = r.get("tipo_relacion") or ""
        m = signed_multiplier(tc, tr)
        if m == 0:
            continue
        sub  = float(r.get("subtotal") or 0)
        iva  = float(r.get("impuestos") or 0)
        ret  = float(r.get("retenciones") or 0)
        tot  = float(r.get("total") or 0)

        net["subtotal"]    += m * sub
        net["iva"]         += m * iva
        net["retenciones"] += m * ret
        net["total"]       += m * tot

        # Bucket per tipo for the card breakdown
        if tc == "I":
            net["ingresos_n"]    += 1
            net["ingresos_sub"]  += sub
            net["ingresos_iva"]  += iva
            net["ingresos_total"]+= tot
        elif tc == "E" and tr in ("01", "03"):
            net["notas_n"]     += 1
            net["notas_sub"]   += sub
            net["notas_iva"]   += iva
            net["notas_total"] += tot
        elif tc == "E" and tr == "07":
            net["anticipos_n"]    += 1
            net["anticipos_sub"]  += sub
            net["anticipos_iva"]  += iva
            net["anticipos_total"]+= tot
    return net
```

**Importante:** la función `compute_net_totals` es la **única fuente de verdad** para los totales — debe usarse tanto en el card resumen del portal como en el exporter de Excel para garantizar que los números coincidan en todas las vistas.

### Paso 5 — UI: badge con label humano + signo en monto

Modificar `templates/partials/received_list.html` (o el partial equivalente que renderea la tabla de recibidas). Buscar dónde se pinta `tipo_comprobante` y reemplazar por:

```jinja
{% set label = row.tipo_label %}  {# computed in route #}
{% set is_neg = row.signed_amount < 0 %}
<span class="badge badge--{{ row.badge_color }} badge--xs">{{ label }}</span>
```

Donde `badge_color` se mapea:

- "Ingreso" → `info` (azul)
- "Nómina" → `neutral`
- "Pago (REP)" → `accent`
- "Nota de crédito" / "Devolución" → `warn` (rojo/naranja)
- "Anticipo aplicado" → `ppd` (amarillo tenue)
- "Sustitución" → `neutral`

El monto se pinta con signo y color: negativo en `var(--danger)` o `var(--warn)`, positivo normal.

En `routers/api/invoices/received_list.py` (o equivalente):

```python
from services.sat.cfdi_relacion_labels import label_for_received, signed_amount

# en la serialización:
row["tipo_label"] = label_for_received(row["tipo_comprobante"], row["tipo_relacion"])
row["signed_amount"] = signed_amount(row["total"], row["tipo_comprobante"], row["tipo_relacion"])
```

Verificar que `tipo_relacion` se devuelva en el SELECT del query.

### Paso 6 — Card resumen arriba de la tabla "Recibidas" (con IVA neto)

**Objetivo crítico:** los totales arriba del listado deben mostrar **TODOS los campos fiscales con su neto correcto**: subtotal, IVA acreditable, retenciones, total. Las notas de crédito (TipoRelacion 01/03) y anticipos aplicados (07) **restan también su IVA** porque no se puede acreditar IVA dos veces (en la compra original y luego de nuevo en la nota).

**Cálculo en la ruta** (usar el helper único `compute_net_totals` para que portal y Excel coincidan exactamente):

```python
from services.sat.cfdi_relacion_labels import compute_net_totals, label_for_received, signed_amount

# en la serialización por fila:
for row in rows:
    row["tipo_label"] = label_for_received(row["tipo_comprobante"], row.get("tipo_relacion"))
    row["signed_total"] = signed_amount(row["total"], row["tipo_comprobante"], row.get("tipo_relacion"))

# Totales del mes — fuente única de verdad
stats = compute_net_totals(rows)
# stats expone:
#   subtotal, iva, retenciones, total  ← netos del periodo (lo que va al SAT)
#   ingresos_n / ingresos_sub / ingresos_iva / ingresos_total
#   notas_n / notas_sub / notas_iva / notas_total
#   anticipos_n / anticipos_sub / anticipos_iva / anticipos_total
```

**Template** — la card resumen separa cada concepto fiscal con su columna para que el usuario VEA cómo se construye el neto:

```html
<div class="recibidas-resumen">
  <!-- Fila 1: tarjetas por tipo (cuenta) -->
  <div class="resumen-cards">
    <div class="resumen-card resumen-card--pos">
      <span class="resumen-card__label">Compras (Ingresos)</span>
      <span class="resumen-card__amount">${{ "{:,.2f}".format(stats.ingresos_total) }}</span>
      <span class="resumen-card__count">{{ stats.ingresos_n }} facturas</span>
    </div>
    <div class="resumen-card resumen-card--neg">
      <span class="resumen-card__label">Notas y devoluciones</span>
      <span class="resumen-card__amount">−${{ "{:,.2f}".format(stats.notas_total) }}</span>
      <span class="resumen-card__count">{{ stats.notas_n }} notas</span>
    </div>
    <div class="resumen-card resumen-card--info">
      <span class="resumen-card__label">Anticipos aplicados</span>
      <span class="resumen-card__amount">−${{ "{:,.2f}".format(stats.anticipos_total) }}</span>
      <span class="resumen-card__count">{{ stats.anticipos_n }} · ya deducidos</span>
    </div>
  </div>

  <!-- Fila 2: desglose fiscal NETO (lo que va al SAT) -->
  <div class="resumen-fiscal">
    <div class="resumen-fiscal__col">
      <span class="resumen-fiscal__label">Gasto deducible (subtotal)</span>
      <span class="resumen-fiscal__amount">${{ "{:,.2f}".format(stats.subtotal) }}</span>
      <span class="resumen-fiscal__detail muted">
        {{ "{:,.2f}".format(stats.ingresos_sub) }}
        − {{ "{:,.2f}".format(stats.notas_sub) }}
        − {{ "{:,.2f}".format(stats.anticipos_sub) }}
      </span>
    </div>
    <div class="resumen-fiscal__col">
      <span class="resumen-fiscal__label">IVA acreditable</span>
      <span class="resumen-fiscal__amount">${{ "{:,.2f}".format(stats.iva) }}</span>
      <span class="resumen-fiscal__detail muted">
        {{ "{:,.2f}".format(stats.ingresos_iva) }}
        − {{ "{:,.2f}".format(stats.notas_iva) }}
        − {{ "{:,.2f}".format(stats.anticipos_iva) }}
      </span>
    </div>
    {% if stats.retenciones != 0 %}
    <div class="resumen-fiscal__col">
      <span class="resumen-fiscal__label">Retenciones</span>
      <span class="resumen-fiscal__amount">${{ "{:,.2f}".format(stats.retenciones) }}</span>
    </div>
    {% endif %}
    <div class="resumen-fiscal__col resumen-fiscal__col--total">
      <span class="resumen-fiscal__label">Total del mes</span>
      <span class="resumen-fiscal__amount">${{ "{:,.2f}".format(stats.total) }}</span>
    </div>
  </div>
</div>
```

**Estilos** (sleek, hairline borders, tabular-nums para alineación de números):

```css
.recibidas-resumen { margin: 0 0 18px; }
.resumen-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin-bottom: 10px; }
.resumen-card { background: var(--surface-2); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; }
.resumen-card__label { display: block; font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: .04em; margin-bottom: 4px; }
.resumen-card__amount { display: block; font-size: 18px; font-weight: 700; font-variant-numeric: tabular-nums; }
.resumen-card__count { display: block; font-size: 11px; color: var(--text-muted); margin-top: 2px; }
.resumen-card--pos .resumen-card__amount { color: var(--text); }
.resumen-card--neg .resumen-card__amount { color: var(--danger, #dc2626); }
.resumen-card--info .resumen-card__amount { color: var(--warn, #d97706); }

.resumen-fiscal { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; padding: 14px 16px; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; }
.resumen-fiscal__col { display: flex; flex-direction: column; gap: 3px; }
.resumen-fiscal__col--total { border-left: 1px solid var(--border); padding-left: 12px; }
.resumen-fiscal__label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: .04em; }
.resumen-fiscal__amount { font-size: 17px; font-weight: 700; font-variant-numeric: tabular-nums; }
.resumen-fiscal__detail { font-size: 11px; font-family: var(--font-mono, monospace); }
.resumen-fiscal__col--total .resumen-fiscal__amount { color: var(--accent); }
```

**Por qué el IVA tiene que restar las notas y anticipos:**

| Caso | IVA en la factura I | IVA en la NC/Anticipo | IVA acreditable real |
|---|---|---|---|
| Compra normal $1,000 + IVA $160 | $160 | — | $160 (suma) |
| NC por devolución total | — | −$160 | $0 (se cancela) |
| Anticipo de feb ya acreditado en feb | — | −$160 | $0 (no se acredita 2 veces) |

Si el portal mostrara IVA acreditable de $160 cuando hay una NC que lo cancela, el usuario declararía IVA que no existe → multa del SAT. Por eso la fórmula `IVA neto = IVA ingresos − IVA notas − IVA anticipos` es **obligatoria** y debe coincidir con la prellenada del SAT.

### Paso 7 — Actualizar el exporter de contabilidad (mismo cálculo de IVA neto)

En `scripts/export_contabilidad.py`:

- Importar `compute_net_totals` desde `services.sat.cfdi_relacion_labels` para que el Excel y el portal usen **exactamente la misma fórmula** y nunca discrepen.
- En la hoja "Mensual" por usuario, reemplazar las columnas actuales por:
  - Subtotal gastos NETO (con resta de notas + anticipos)
  - IVA acreditable NETO (con resta de notas + anticipos)
  - Retenciones NETO
  - Total gastos NETO
- Añadir filas de detalle ANTES del total para que el contador vea cómo se construye el neto:
  - "Compras (Ingresos)" → suma positiva
  - "Notas de crédito y devoluciones" → resta
  - "Anticipos aplicados" → resta
  - "**TOTAL NETO**" → en negritas, color destacado
- En el detalle de cada CFDI (hoja "Gastos"), añadir columna **Tipo (label)** justo después de la columna `Tipo` (código).
- En el resumen general, recalcular utilidad fiscal usando el subtotal neto correcto.

Verificar con el caso real de Manuel (May 2026): el subtotal de gastos NETO debe quedar cercano a $25,227 (lo que SAT muestra como "Compras facturadas del mes" en la prellenada), no a $80,627. Esa coincidencia con la prellenada es la prueba de que el cálculo es correcto.

### Paso 8 — Tests

Crear `tests/test_cfdi_tipo_relacion.py`:

```python
from services.sat.cfdi_relacion_labels import label_for_received, signed_amount

def test_ingreso_recibido_suma():
    assert label_for_received("I", None) == "Ingreso"
    assert signed_amount(100, "I", None) == 100

def test_nota_credito_resta():
    assert label_for_received("E", "01") == "Nota de crédito"
    assert signed_amount(100, "E", "01") == -100

def test_devolucion_resta():
    assert label_for_received("E", "03") == "Devolución"
    assert signed_amount(100, "E", "03") == -100

def test_anticipo_aplicado_resta():
    assert label_for_received("E", "07") == "Anticipo aplicado"
    assert signed_amount(100, "E", "07") == -100

def test_sustitucion_neutral():
    assert label_for_received("E", "04") == "Sustitución"
    assert signed_amount(100, "E", "04") == 0

def test_pago_neutral():
    assert label_for_received("P", None) == "Pago (REP)"
    assert signed_amount(100, "P", None) == 0

def test_egreso_sin_relacion_resta_conservador():
    # Si llega un Egreso sin TipoRelacion, asumir nota de crédito (conservador)
    assert signed_amount(100, "E", None) == -100


# ── Tests del cálculo NETO (IVA y todos los campos fiscales) ──
from services.sat.cfdi_relacion_labels import compute_net_totals

def test_compute_net_resta_iva_de_notas():
    rows = [
        {"tipo_comprobante": "I", "tipo_relacion": None,
         "subtotal": 1000, "impuestos": 160, "retenciones": 0, "total": 1160},
        {"tipo_comprobante": "E", "tipo_relacion": "01",  # nota de crédito
         "subtotal": 500,  "impuestos": 80,  "retenciones": 0, "total": 580},
    ]
    n = compute_net_totals(rows)
    assert n["subtotal"] == 500    # 1000 - 500
    assert n["iva"] == 80          # 160 - 80   ← IVA acreditable real
    assert n["total"] == 580       # 1160 - 580


def test_compute_net_resta_iva_de_anticipo_aplicado():
    # Caso real Manuel: factura I + Egreso 07 mismo monto = neto 0 en TODOS los campos
    rows = [
        {"tipo_comprobante": "I", "tipo_relacion": None,
         "subtotal": 71649.57, "impuestos": 11463.93, "retenciones": 0, "total": 83113.50},
        {"tipo_comprobante": "E", "tipo_relacion": "07",  # anticipo aplicado
         "subtotal": 71649.57, "impuestos": 11463.93, "retenciones": 0, "total": 83113.50},
    ]
    n = compute_net_totals(rows)
    assert abs(n["subtotal"]) < 0.01
    assert abs(n["iva"]) < 0.01           # IVA tampoco se acredita dos veces
    assert abs(n["total"]) < 0.01


def test_compute_net_sustitucion_es_neutral():
    # TipoRelacion 04 NO debe sumar ni restar
    rows = [
        {"tipo_comprobante": "I", "tipo_relacion": None,
         "subtotal": 1000, "impuestos": 160, "retenciones": 0, "total": 1160},
        {"tipo_comprobante": "E", "tipo_relacion": "04",  # sustitución
         "subtotal": 500,  "impuestos": 80,  "retenciones": 0, "total": 580},
    ]
    n = compute_net_totals(rows)
    assert n["subtotal"] == 1000   # sustitución no se cuenta
    assert n["iva"] == 160
    assert n["total"] == 1160


def test_compute_net_pagos_no_afectan():
    rows = [
        {"tipo_comprobante": "I", "tipo_relacion": None,
         "subtotal": 1000, "impuestos": 160, "retenciones": 0, "total": 1160},
        {"tipo_comprobante": "P", "tipo_relacion": None,
         "subtotal": 0, "impuestos": 0, "retenciones": 0, "total": 0},
    ]
    n = compute_net_totals(rows)
    assert n["subtotal"] == 1000
    assert n["iva"] == 160


def test_compute_net_buckets_for_resumen_card():
    rows = [
        {"tipo_comprobante": "I", "tipo_relacion": None,
         "subtotal": 1000, "impuestos": 160, "retenciones": 0, "total": 1160},
        {"tipo_comprobante": "I", "tipo_relacion": None,
         "subtotal": 2000, "impuestos": 320, "retenciones": 0, "total": 2320},
        {"tipo_comprobante": "E", "tipo_relacion": "01",
         "subtotal": 100,  "impuestos": 16,  "retenciones": 0, "total": 116},
        {"tipo_comprobante": "E", "tipo_relacion": "07",
         "subtotal": 500,  "impuestos": 80,  "retenciones": 0, "total": 580},
    ]
    n = compute_net_totals(rows)
    # Buckets para la card
    assert n["ingresos_n"] == 2
    assert n["ingresos_iva"] == 480  # 160 + 320
    assert n["notas_n"] == 1
    assert n["notas_iva"] == 16
    assert n["anticipos_n"] == 1
    assert n["anticipos_iva"] == 80
    # Netos
    assert n["subtotal"] == 2400   # 3000 - 100 - 500
    assert n["iva"] == 384         # 480 - 16 - 80
    assert n["total"] == 2784      # 3480 - 116 - 580
```

Y un test de integración que verifique la card resumen renderea con los números correctos para un issuer mock.

### Paso 9 — QA manual y validación

1. Aplicar migración: arrancar el server, confirmar que las columnas existen.
2. Backfill: `.venv/bin/python scripts/backfill_tipo_relacion.py` — confirmar que para Manuel (issuer 11) en mayo, la factura E folio 2785 (UUID `88930fce-9f3b-418d-bafc-0c1e24207867`) queda con `tipo_relacion = '07'`.
3. UI: navegar a `/portal/invoices/received?ym=2026-05` con el cookie de Manuel y verificar:
   - Badge "Anticipo aplicado" en la factura E
   - Monto negativo en rojo
   - Card resumen muestra "Anticipos aplicados: −$83,113" y neto correcto
4. Regenerar Excel: `.venv/bin/python scripts/export_contabilidad.py` y abrir el archivo.
5. Tests: `.venv/bin/pytest -q tests/test_cfdi_tipo_relacion.py` debe pasar 100%.

---

## Acceptance criteria

- [ ] Migración 065 aplicada, idempotente, sin perder datos
- [ ] Parser XML extrae `TipoRelacion` y `CfdiRelacionado/UUID` para nuevos CFDI
- [ ] Backfill ejecutado con éxito sobre Egresos existentes (0 errores fatales)
- [ ] Manuel (issuer_id=11) UUID `88930fce-9f3b-418d-bafc-0c1e24207867` tiene `tipo_relacion='07'`
- [ ] UI muestra badge "Anticipo aplicado" en amarillo tenue para esa factura
- [ ] El monto se ve negativo (`−$83,113`) en la fila
- [ ] Card resumen "Anticipos aplicados" muestra el monto correcto
- [ ] La segunda fila de la card resumen muestra **subtotal neto, IVA neto y total neto** con el desglose visible
- [ ] El **IVA acreditable** del mes resta correctamente el IVA de las notas y anticipos (no solo el subtotal)
- [ ] Neto del mes para Manuel coincide con la prellenada del SAT (subtotal ≈ $25,227, no $80,627)
- [ ] Excel `contabilidad_2026-05.xlsx` separa columnas/filas para notas vs anticipos y muestra IVA neto
- [ ] El IVA neto en Excel = IVA en portal (mismo helper `compute_net_totals`)
- [ ] Tests unitarios pasan (`tests/test_cfdi_tipo_relacion.py`)
- [ ] `.venv/bin/pytest -q` no introduce nuevas fallas (baseline = 12 pre-existentes)
- [ ] `.venv/bin/python -c "import app"` sigue limpio

---

## Logging requerido

Al final del job, escribir `context/implement/2026-06-15-cfdi-tipo-relacion-egresos.md` con:

- Resumen de cambios por archivo
- Conteo de filas backfilled
- Resultados del pytest (passed/failed)
- Cualquier desviación del plan y por qué
- Screenshots o salida de comandos clave (opcional)

---

## Notas para el ejecutor autónomo

- Cuando termines, no hagas commit a menos que el usuario te lo pida explícitamente.
- Si encuentras un bloqueador (ej. XML con estructura inesperada), documéntalo en el log e intenta seguir con el resto. No abandones el job por un caso edge.
- Si las pruebas pre-existentes empiezan a fallar más, sí abortar — significa que rompiste algo.
- Lenguaje en código: inglés. Lenguaje en UI: español MX.
