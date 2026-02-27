# Módulo bancario — Flujo y estado actual

Resumen del módulo de **Movimientos** y **Estados de cuenta**: flujo end-to-end, endpoints clave, qué persiste y próximos pasos.

---

## 1. Flujo actual (resumen)

1. **Convertir Edo. de Cuenta** (`/portal/bank/pdf-to-excel`):
   - **Mis cuentas bancarias** (arriba): CRUD de cuentas propias para detectar traspasos.
   - **Dropzone**: uno o varios PDFs → preview en memoria (multi-PDF o preview-json).
   - **Tabla consolidada**: movimientos con filtros (Todos, Revisar, Cuenta propia, Financiero, Duplicados, Ingresos, Gastos).
   - **Guardar movimientos**: selector de cuenta + botón «Guardar movimientos» → `POST /portal/bank/preview/commit` (persiste desde preview sin re-subir PDF).
   - **Guardar con validación**: formulario con cuenta + PDF → `POST /portal/bank/statements/ingest` (sube PDF y persiste).

2. **Movimientos** (`/portal/bank/movements` o `/portal/movimientos`):
   - Lista movimientos guardados con filtros (period_month, statement_id, tipo, categoría, cfdi_match_status, búsqueda).
   - Totales: ingresos, gastos.
   - Enlaces a confirmar/rechazar sugerencias de factura.

3. **Estados de cuenta** (`/portal/bank/statements`):
   - Lista de estados de cuenta guardados (por periodo, banco, cuenta).

---

## 2. Endpoints clave

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/portal/bank/accounts` | Lista cuentas bancarias del issuer |
| POST | `/portal/bank/accounts` | Crear cuenta |
| PUT | `/portal/bank/accounts/{id}` | Actualizar cuenta |
| DELETE | `/portal/bank/accounts/{id}` | Eliminar cuenta |
| POST | `/portal/bank/pdf-to-excel/preview-json` | Preview 1 PDF (JSON) |
| POST | `/portal/bank/pdf-to-excel/preview-multi` | Preview N PDFs (consolidado) |
| POST | `/portal/bank/preview/commit` | Persistir movimientos del preview (sin PDF) |
| POST | `/portal/bank/statements/ingest` | Ingesta PDF + cuenta (validación RFC/cuenta) |
| POST | `/portal/bank/preview/export` | Exportar preview a Excel |
| POST | `/portal/bank/preview/reclassify` | Re-clasificar con preset (conservative/aggressive) |
| POST | `/portal/bank/matches/{id}/confirm` | Confirmar sugerencia movimiento–CFDI |
| POST | `/portal/bank/matches/{id}/reject` | Rechazar sugerencia |
| GET | `/portal/bank/movements` | Página movimientos (filtros) |
| GET | `/portal/bank/statements` | Página estados de cuenta |

---

## 3. Qué persiste y qué no

- **Persiste**:
  - **Mis cuentas bancarias**: tabla `issuer_bank_accounts`.
  - **Estados de cuenta**: tabla `bank_statements` (metadata + source_pdf_sha256 / fingerprint preview).
  - **Movimientos**: tabla `bank_movements` (por statement, con duplicate_hash para dedupe).
  - **Sugerencias movimiento–CFDI**: tabla `bank_invoice_matches` (suggested / confirmed / rejected).
- **No persiste** (solo en memoria/sesión):
  - Preview multi-PDF hasta que el usuario pulse «Guardar movimientos» o use «Guardar con validación» con un PDF.

---

## 4. Deduplicación

- **Statement**:
  - Ingest con PDF: por `issuer_id` + `source_pdf_sha256` (mismo PDF = no reinsertar statement ni movimientos).
  - Preview commit: por fingerprint sintético (`preview|issuer_id|bank_account_id|period_month|bank_name|account_last4|count|first_fp|last_fp`). Mismo preview lógico = no reinsertar.
- **Movimiento**:
  - Antes de insertar se comprueba si ya existe un movimiento con el mismo `bank_account_id` y `duplicate_hash` (fingerprint: fecha, monto dep/ret, saldo, concepto, cve, archivo). Si existe, no se inserta y se cuenta como `duplicate_movements_count`.
- Respuesta típica: `inserted_count`, `duplicate_movements_count`, `duplicate_statement` (si aplica).

---

## 5. Validación al guardar

- **RFC**: Si el PDF/statement trae RFC de titular y la cuenta seleccionada tiene RFC, deben coincidir.
- **Cuenta**: La cuenta debe existir y pertenecer al issuer. Opcionalmente se valida últimos 4 dígitos contra el PDF.
- Servicio: `services/bank_statement_ingest.py` (`validate_statement_ownership`, `extract_statement_metadata`).

---

## 6. Sugerencias movimiento ↔ CFDI

- Tras insertar movimientos (ingest o preview/commit), para los que tienen `requires_cfdi` se buscan candidatos CFDI (`services/bank_cfdi_matching.py`: `find_cfdi_candidates`, `save_suggested_matches`).
- En la página Movimientos se muestran badges por fila (Factura vinculada / Sugerencia (N) / Sin factura) y acciones para confirmar/rechazar.

---

## 7. Próximos pasos (backlog)

- **Dashboard de conciliación**: KPIs claros en Movimientos (ingresos reales, gastos reales, traspasos cuenta propia, sin factura, pendientes por revisar).
- **UX página PDF**: Una sola tabla consolidada, orden 1) Cuentas 2) Dropzone 3) Tabla 4) KPIs 5) Guardar movimientos (ya mayormente así).
- **Detección cuentas propias**: Ya existe en preview (`bank_own_accounts`, CLABE, últimos 4, titular); asegurar que al persistir se guarde `es_transferencia_propia_probable` y se use en KPIs.
- **Match CFDI**: Ya hay base (tabla, scoring, confirm/reject); reforzar badges y flujo en UI.

---

## 8. Sanity check rápido

- Página PDF preview abre y multi-upload funciona.
- Edición concepto/categoría en la tabla preview funciona.
- «Guardar movimientos» (preview/commit) pide cuenta, confirma y persiste; muestra «Ver movimientos guardados».
- «Guardar con validación» (ingest) sube PDF y persiste; mismo PDF dos veces no duplica.
- Página Movimientos abre y lista datos con filtros.
- Página Estados de cuenta abre sin error 500.
- `_render_portal` acepta `extra_context` y `**template_vars` para evitar 500 por kwargs en rutas bancarias.
