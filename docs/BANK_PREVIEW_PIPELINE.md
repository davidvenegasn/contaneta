# Flujo preview estados de cuenta (multi-PDF, sin DB)

## Qué hace

- **Multi-upload**: El usuario puede subir uno o varios PDFs de estados de cuenta en una sola carga.
- **Procesamiento por archivo**: Cada PDF se procesa de forma aislada; si uno falla, el resto se muestra.
- **Vista consolidada**: Movimientos de todos los archivos en una sola tabla, con columnas Banco y Archivo origen.
- **Resumen global y por archivo**: Totales de ingresos/gastos, conteos (financiero, revisar), y por archivo: nombre, banco detectado, movimientos, subtotales.
- **Sin persistencia**: No se escribe en `bank_movements` ni en ninguna tabla; todo es en memoria y en la respuesta/render.

## Qué no hace

- No guarda movimientos en base de datos.
- No modifica `bank_movements` ni tablas de estados de cuenta.
- No hace conciliación con CFDI en este flujo.

## Endpoints

| Método | Ruta | Uso |
|--------|------|-----|
| GET | `/portal/bank/pdf-to-excel` | Pantalla HTML (upload + preview) |
| POST | `/portal/bank/pdf-to-excel/preview-json` | Un solo PDF → JSON (compatibilidad) |
| POST | `/portal/bank/pdf-to-excel/preview-multi` | Varios PDFs → JSON consolidado |

## Contrato respuesta multi

```json
{
  "ok": true,
  "movements": [ { ... } ],
  "global_summary": {
    "files_processed": 2,
    "files_with_errors": 0,
    "total_movements": 45,
    "total_ingresos": 1000.00,
    "total_gastos": 500.00,
    "count_ingreso": 10,
    "count_gasto": 30,
    "count_info": 5,
    "count_financiero": 3,
    "count_low_confidence": 2
  },
  "files_summary": [ { "file_name": "...", "bank_name": "BANORTE", "movements_count": 20, ... } ],
  "file_errors": [ { "file_name": "...", "error": "..." } ],
  "file_warnings": [ { "file_name": "...", "warnings": ["..."] } ],
  "generated_at": "2025-..."
}
```

## Cómo está separada la clasificación

- **Detección de banco**: `services/bank_detection.py` — `detect_bank_from_text` / `detect_bank_from_pdf_text_pages`. Reglas: BANORTE, CUENTA ENLACE PERSONAL → `banorte_v1`; resto → `generic_v1`.
- **Pipeline por archivo**: `services/bank_preview_pipeline.py` — `parse_bank_statement_preview(pdf_bytes, file_name, file_index)`. Extrae texto, detecta banco, llama parser Banorte (reutiliza `bank_statement_parser` + `bank_parse_preview._build_movement`), devuelve movimientos en formato preview y resumen por archivo.
- **Clasificación por reglas**: En `bank_parse_preview` (`_classify`) y opcionalmente `services/bank_classifier.py` (`classify_bank_preview_movement`). Asignan tipo, canal, categoría, flags financieros y confianza.
- **Concepto resumen**: `services/bank_concept_summary.py` — `build_concept_summary(mov)` para descripciones cortas legibles.

## Cómo agregar un nuevo banco

1. En `services/bank_detection.py`: añadir reglas en `detect_bank_from_text` (p. ej. si "BBVA" en texto → `bank_name="BBVA"`, `profile="bbva_v1"`).
2. En `services/bank_preview_pipeline.py`: en `parse_bank_statement_preview`, después de `detect_bank_from_pdf_text_pages`, si `profile == "bbva_v1"` llamar a un nuevo `_parse_bbva(raw_rows, ...)` (implementar extracción de líneas y montos al estilo de Banorte).
3. Crear en `services/` un módulo o funciones que, a partir de `raw_rows`, devuelvan lista de dicts con los campos del preview (usar `bank_preview_models.make_preview_movement`).
4. Mantener fallback a `_parse_banorte` o genérico si el perfil no está implementado.

## Límites y seguridad

- Solo PDF (validación por extensión y opcionalmente Content-Type).
- Máximo 10 archivos por carga (`MAX_BANK_PDF_FILES`).
- Máximo 15 MB por archivo y 50 MB total por carga (`MAX_BANK_PDF_SIZE`, `MAX_BANK_PDF_TOTAL_SIZE`).
- No se persiste contenido sensible en logs; errores amigables al usuario ("No se pudo reconocer el formato del estado de cuenta", etc.).

## Próximo paso sugerido

- Persistencia opcional: permitir “Guardar movimientos” desde el preview hacia `bank_movements` (con dedupe por hash o clave).
- Conciliación con CFDI: cruce de movimientos bancarios con facturas recibidas/emitidas por RFC, CVE, monto y fecha.

## Cómo probar manualmente

1. **Un PDF Banorte**: Ir a `/portal/bank/pdf-to-excel`, seleccionar un PDF → se procesa solo y se muestra la tabla actual (vista previa single).
2. **Varios PDFs**: Seleccionar 2 o más PDFs (o arrastrar varios) → aparece la lista de archivos → clic en «Procesar estados de cuenta» → se llama a `preview-multi`, se muestra la vista consolidada con resumen global, resumen por archivo y tabla con columnas Banco y Archivo.
3. **Un archivo inválido entre varios**: Subir por ejemplo un .txt y dos .pdf → el inválido debe aparecer en errores por archivo; los PDFs válidos deben procesarse.
4. **Límites**: Probar con más de 10 archivos (debe rechazar) y con un PDF > 15 MB (debe rechazar).
