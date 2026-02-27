# Fase 0 — Revisión flujo actual (Módulo Movimientos)

## 1) Flujo actual

- **Subida PDF**: `POST /portal/bank/pdf-to-excel/upload` (un archivo). Sin `preview=1` guarda PDF, crea fila en `bank_statements` (dedupe por sha256), llama `convert_pdf_to_xlsx()`, crea `bank_pdf_exports` con `file_id`, inserta movimientos en `bank_movements` con `statement_file_id = file_id`.
- **Preview (sin DB)**: `POST /portal/bank/pdf-to-excel/preview-multi` (varios PDFs) → `parse_bank_statement_preview()` → JSON con movimientos en memoria; no persiste.
- **Vista temporal**: La página "Convertir Edo. de Cuenta" muestra preview en memoria. La persistencia ocurre solo al hacer "upload" (export) que usa `convert_pdf_to_xlsx` (flujo distinto al preview-multi).

## 2) Endpoints y estructura

| Qué | Dónde |
|-----|--------|
| Subida/guardar PDF + movimientos | `POST /portal/bank/pdf-to-excel/upload` |
| Preview (multi-PDF, memoria) | `POST /portal/bank/pdf-to-excel/preview-multi` |
| Listado estados | `GET /portal/bank/statements` (usa `bank_pdf_exports`) |
| Listado movimientos | `GET /portal/bank/movements` (filtros: statement_id, tipo, categoria, search) |
| issuer_id | `get_portal_issuer` (sesión) |

**Movimiento actual en DB** (`bank_movements`):  
`id`, `issuer_id`, `statement_file_id` (TEXT = file_id), `fecha`, `descripcion`, `deposito`, `retiro`, `saldo`, `tipo`, `categoria`, `metodo_hint`, `contraparte_hint`, `rfc_encontrado`, `confidence_score`, `source_page_first`, `created_at`.

**Movimiento en preview (memoria)**:  
`fecha`, `concepto_resumen`, `raw_text_original`, `monto_deposito`, `monto_retiro`, `tipo_movimiento`, `categoria_sugerida`, `contraparte_nombre`, `rfc_detectado`, `clabe_detectada`, `es_transferencia_propia_probable`, `impacta_contabilidad`, etc.

## 3) Modelo actual

- **Cuentas bancarias**: `issuer_bank_accounts` (id, issuer_id, alias, bank_name, clabe, account_last4, holder_name, rfc_titular, is_active). Sin `account_type` ni `holder_rfc` explícito (rfc_titular existe).
- **Estados de cuenta**: `bank_statements` (id, issuer_id, bank_name, account_last4, period_start, period_end, source_pdf_path, source_pdf_sha256). Sin `bank_account_id`, `status`, `file_sha256` como nombre, ni `period_month`.
- **Export por archivo**: `bank_pdf_exports` (file_id, pdf_path, xlsx_path, meta_json). Los movimientos referencian `statement_file_id` = este `file_id`.
- **sat_cfdi** (para matching): issuer_id, direction, uuid, fecha_emision, rfc_emisor, nombre_emisor, rfc_receptor, nombre_receptor, total, status, xml_path. Índice (issuer_id, direction, fecha_emision).

## 4) Decisiones para no romper

- No reescribir parser; reutilizar `parse_bank_statement_preview` y/o `convert_pdf_to_xlsx` según flujo.
- Añadir columnas a tablas existentes vía migraciones; no eliminar `statement_file_id` hasta tener todo migrado a `bank_statement_id`.
- Mantener flujo preview-multi como está (solo memoria); el flujo que persiste puede ser el actual upload o un nuevo “guardar desde preview” que use el mismo parser y escriba en las tablas nuevas/ampliadas.
