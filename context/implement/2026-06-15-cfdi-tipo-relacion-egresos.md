# Implementation Log: CFDI TipoRelacion para Egresos

**Date:** 2026-06-16 (updated)
**Plan:** context/plan/2026-06-15-cfdi-tipo-relacion-egresos.md

---

## Changes by File

### New files
| File | Lines | Description |
|------|-------|-------------|
| `migrations/065_cfdi_tipo_relacion.sql` | 8 | ADD COLUMN IF NOT EXISTS tipo_relacion, related_uuids + index |
| `services/sat/cfdi_relacion_labels.py` | 143 | Labels, badge colors, signed_amount(), signed_multiplier(), compute_net_totals() |
| `scripts/backfill_tipo_relacion.py` | 89 | Backfill existing Egresos from XML files |
| `tests/test_cfdi_tipo_relacion.py` | ~160 | 39 unit tests for labels, signed amounts, multiplier, compute_net_totals |

### Modified files
| File | Changes |
|------|---------|
| `sat_sync/parse_xml.php` | Extract CfdiRelacionados → tipo_relacion + related_uuids (JSON). Updated UPDATE stmt + all 3 execute() calls. |
| `routers/api/invoices/received_list.py` | Added tipo_comprobante + tipo_relacion to SELECT. Enrichment with tipo_label, badge_color, signed_total. |
| `routers/portal/invoices.py` | Added subtotal, tipo_comprobante, tipo_relacion to received query. Import compute_net_totals. Compute `stats` from vigente rows and pass to template. |
| `templates/partials/received_list.html` | Resumen card: 2-row layout — Row 1: Compras/NC/Anticipos breakdown. Row 2: Subtotal neto, IVA neto, Retenciones, Total neto deducible. Badge column + signed totals in table. |
| `templates/portal_received.html` | Same resumen card upgrade as partial. Badge column + signed total with red negatives. |
| `static/css/components.css` | Added `.metric-card--warn`, `--accent`, `--highlight` variants + `.u-mt-3` utility. |
| `scripts/export_contabilidad.py` | tipo_relacion in query. "Tipo (label)" column. Monthly summary separates NC/Dev, Anticipos, shows Gasto neto deducible. |

---

## Backfill Results

```
Processing 31 Egresos...
OK: 31  errors: 0  missing-xml: 0
```

---

## Test Results

```
39 new tests: ALL PASSED
Full suite: 928 passed, 12 failed (pre-existing), 4 skipped, 9 deselected
Delta: +0 new failures
```

`python -c "import app"` → OK

---

## Acceptance Criteria Status

- [x] Migración 065 aplicada, idempotente (IF NOT EXISTS), sin perder datos
- [x] Parser XML (PHP) extrae TipoRelacion y CfdiRelacionado/UUID para nuevos CFDI
- [x] Backfill ejecutado con éxito: 31 Egresos, 0 errores
- [x] UI muestra badge por tipo (Ingreso, NC, Anticipo, etc.) con color semántico
- [x] El monto se ve negativo (−$X) en la fila para NC/anticipos (red via var(--danger))
- [x] Card resumen con breakdown: Compras / NC+Dev / Anticipos + fiscales netos (subtotal, IVA, retenciones, total neto deducible)
- [x] Neto del mes correcto en Excel (separado NC/anticipos)
- [x] Excel contabilidad separa columnas para NC/Dev vs Anticipos
- [x] Tests unitarios pasan (39/39)
- [x] pytest -q no introduce nuevas fallas
- [x] `import app` limpio

---

## Key Functions Added

- `signed_multiplier(tc, tr)` → +1 / -1 / 0 for ALL fiscal fields
- `compute_net_totals(rows)` → net subtotal, IVA, retenciones, total + bucket breakdown (ingresos_n/total, notas_n/total, anticipos_n/total)
