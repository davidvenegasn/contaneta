# Flujo de preview de estados de cuenta (multi-PDF, sin DB)

Documentación del módulo de carga de estados de cuenta en PDF para generar un **preview consolidado de movimientos** en memoria: mejor parsing, clasificación por reglas y edición sencilla en UI. **Los movimientos no se guardan en base de datos.** Sí se guarda la configuración de **Mis cuentas bancarias** (tabla `issuer_bank_accounts`) para detectar traspasos entre cuentas propias.

---

## 1. Flujo multi-PDF preview (una sola lista)

1. **Pantalla**: Título «Movimientos bancarios (preview)», bloque **Mis cuentas bancarias** (arriba del dropzone), dropzone multi-PDF y **una sola** sección de resultados (lista consolidada).
2. **Frontend**: El usuario puede agregar sus cuentas bancarias (alias, banco, CLABE, últimos 4, titular) para que el sistema marque transferencias entre cuentas propias. Luego selecciona o arrastra uno o varios PDFs y pulsa «Procesar estados de cuenta».
3. **Envío**: Se llama a `POST /portal/bank/pdf-to-excel/preview-multi` con múltiples `UploadFile`, o a `POST /portal/bank/pdf-to-excel/preview-json` para un solo PDF. En ambos casos la UI muestra la **misma** lista consolidada.
4. **Backend por archivo**:
   - Leer PDF → extraer texto (pdfplumber).
   - Detectar banco y titular del estado de cuenta (`bank_detection`).
   - Parsear movimientos (Banorte u otro perfil).
   - Normalizar campos (`bank_preview_models`).
   - Clasificar por reglas (`bank_classifier`).
   - **Enriquecer con cuentas propias**: cargar `issuer_bank_accounts` activas y llamar a `detect_own_account_transfer` por movimiento (CLABE, últimos 4, nombre titular, RFC).
   - Generar `dedupe_fingerprint`; marcar duplicados en la carga actual.
5. **Respuesta**: `movements`, `global_summary`, `files_summary`, `file_errors`, `file_warnings`. Todo en memoria; sin escritura de movimientos en DB.
6. **UI**: Una sola tabla: Fecha | Banco/Cuenta | Concepto | Tipo | Categoría | Monto | Estado | Acciones. Filtros chips: Todos, Revisar, Cuenta propia, Financiero, Duplicados, Ingresos, Gastos. Detalle expandible por fila.

Si un PDF falla, se muestra el error para ese archivo y se continúa con los demás.

---

## 2. Mis cuentas bancarias (config, sí en DB)

- **Propósito**: Registrar las cuentas propias del usuario para identificar transferencias entre ellas y **no** contarlas como ingreso o gasto real en el resumen.
- **Tabla**: `issuer_bank_accounts` (id, issuer_id, alias, bank_name, clabe, account_last4, holder_name, rfc_titular, is_active, created_at, updated_at).
- **API**: `GET /portal/bank/accounts`, `POST /portal/bank/accounts`, `PUT /portal/bank/accounts/{id}`, `DELETE /portal/bank/accounts/{id}` (protegidos por sesión/issuer).
- **Servicio**: `services/bank_accounts.py` (list_active_accounts, create_account, update_account, delete_account).

---

## 3. Detección de cuenta propia

- **Módulo**: `services/bank_own_accounts.py`.
- **Función**: `detect_own_account_transfer(mov, user_bank_accounts, statement_owner_name=None, statement_owner_rfc=None)`.

Reglas (prioridad alta a baja):

1. **CLABE**: Si en el texto del movimiento aparece una CLABE de 18 dígitos y coincide con la CLABE de una cuenta registrada → **Cuenta propia** (confianza alta).
2. **Últimos 4 dígitos**: Si se detectan últimos 4 de cuenta en el movimiento y coinciden con `account_last4` de una cuenta registrada → **Cuenta propia**.
3. **Nombre titular del estado de cuenta**: Si la contraparte del movimiento coincide con el titular extraído del PDF → **Cuenta propia**.
4. **Titular de cuenta registrada**: Si la contraparte coincide con `holder_name` de alguna cuenta propia → **Cuenta propia**.
5. **RFC**: Si el RFC del movimiento coincide con el RFC del titular del estado o con `rfc_titular` de una cuenta registrada → **Cuenta propia**.

Efectos: `es_transferencia_propia_probable = True`, `impacta_contabilidad = False`, `categoria_sugerida = "CUENTA_PROPIA"`, `subcategoria_sugerida = "TRASPASO_INTERNO"`. Los totales «Ingresos reales» y «Gastos reales» excluyen estos movimientos.

---

## 4. Detección de banco

- **Módulo**: `services/bank_detection.py`.
- **Función**: `detect_bank_from_pdf_text_pages(pages_text)` (o `detect_bank_from_text` según versión).
- **Reglas iniciales**:
  - Si el texto contiene «BANORTE» o «CUENTA ENLACE PERSONAL» → **BANORTE** (perfil `banorte_v1`).
  - Si no → **DESCONOCIDO** (perfil `generic_v1`).
- **Fallback**: Si el banco es DESCONOCIDO, se intenta el parser genérico/Banorte; si no se puede, se devuelve un error amigable por archivo sin tumbar toda la carga.

---

## 5. Clasificación por reglas

- **Módulo**: `services/bank_classifier.py`.
- **Función**: `classify_bank_preview_movement(mov, account_holder_name=None, account_holder_rfc=None)`.

Reglas (prioridad alta a baja):

- **SALDO ANTERIOR** → tipo INFO, no impacta contabilidad.
- **SPEI RECIBIDO** / depósito SPEI → INGRESO, canal SPEI, categoría TRANSFERENCIAS; posible «cuenta propia» (refinado por `bank_own_accounts`).
- **COMPRA ORDEN DE PAGO SPEI** / cargo SPEI → GASTO, SPEI, TRANSFERENCIAS; posible cuenta propia.
- **CARGO POR PAGO CONCENTRACION + TARJETA** → GASTO, TARJETA, TARJETAS_CREDITO, **es_movimiento_financiero**, no impacta contabilidad.
- **AMERICAN EXPRESS** → subcategoría AMEX, categoría TARJETAS_CREDITO si aplica.
- **OXXO** → GASTO, TIENDA_CONVENIENCIA.
- **PAGO REFERENCIADO + IMPUESTO** → GASTO, IMPUESTOS.
- **DEPOSITO DE NOMINA** / NOMINA → INGRESO, NOMINA.
- **CARGO DOMICILIACION** → GASTO, DOMICILIACION, SERVICIOS.
- **RETIRO DE EFECTIVO** / CAJERO → GASTO, EFECTIVO, RETIRO_EFECTIVO.
- **ABONO POR DISPOSICION + TDC** → INGRESO, TARJETA, MOVIMIENTO_FINANCIERO, no impacta contabilidad.

Banderas útiles:

- **impacta_contabilidad**: `False` cuando es financiero o transferencia propia probable.
- **requiere_revision**: `True` cuando confianza &lt; 60, banco desconocido o texto ambiguo.
- **es_transferencia_propia_probable**: refinado por `bank_own_accounts` (CLABE, últimos 4, nombre, RFC).

**Confianza (0–100)**: se ajusta por reglas; si &lt; 60 se añade warning y suele marcar `requiere_revision`.

---

## 6. Significado de los estados (badges)

| Estado           | Significado |
|------------------|-------------|
| **OK**           | Movimiento clasificado con confianza; no requiere revisión. |
| **Revisar**      | Confianza baja o texto ambiguo; conviene revisar concepto/categoría. |
| **Cuenta propia**| Transferencia entre cuentas propias registradas; no cuenta como ingreso/gasto real. |
| **Financiero**   | Pago de tarjeta, disposición, etc.; no impacta ingresos/gastos reales. |
| **Duplicado**    | Posible duplicado en esta carga (misma fecha, monto, concepto/archivo). |

Puede haber más de un badge por movimiento (ej. Cuenta propia + Financiero); en la tabla se muestran los que apliquen.

---

## 7. Campos visibles vs campos técnicos

### En la lista (una sola tabla consolidada)

- Fecha  
- **Banco / Cuenta** (bank_name + account_hint tipo ****9875 + source_file_name)  
- Concepto (editable)  
- Tipo (Ingreso / Gasto / Info)  
- Categoría (editable)  
- Monto  
- Estado: chips **Cuenta propia**, **Financiero**, **Revisar**, **Duplicado** según flags.  
- Acciones (ver detalle / editar)

### En detalle expandible (o modal)

- Banco, Archivo origen, Cuenta (hint)  
- Contraparte, RFC, Referencia, CVE rastreo  
- Texto original (recorte)  
- Warnings y razones de clasificación (ej. «Coincide CLABE con cuenta propia registrada»)  

---

## 8. Qué NO hace (sin DB de movimientos)

- **No** se guardan movimientos en `bank_movements` ni en ninguna otra tabla.
- **No** hay botón «Guardar movimientos» activo (o está desactivado).
- El preview es solo estado en frontend y en la respuesta JSON; se puede exportar a Excel/CSV en memoria.

**Sí** se guarda la configuración de **Mis cuentas bancarias** en `issuer_bank_accounts`.

---

## 9. Próximo paso futuro

- **Persistencia**: Permitir «Guardar movimientos» desde el preview hacia una tabla de movimientos (con `preview_id`, `dedupe_fingerprint` y deduplicación).
- **Conciliación CFDI**: Cruce de movimientos bancarios con facturas recibidas/emitidas por RFC, CVE, monto y fecha.

La estructura interna (modelo preview, `dedupe_fingerprint`, detección de cuenta propia) está lista para esa futura persistencia.

---

## Referencia rápida

| Componente            | Archivo / función |
|-----------------------|-------------------|
| Cuentas bancarias     | `services/bank_accounts.py`; tabla `issuer_bank_accounts`; rutas `/portal/bank/accounts` |
| Detección cuenta propia | `services/bank_own_accounts.py`: `detect_own_account_transfer` |
| Modelo preview        | `services/bank_preview_models.py`: `make_preview_movement`, `compute_dedupe_fingerprint` |
| Detección banco       | `services/bank_detection.py` |
| Pipeline por archivo  | `services/bank_preview_pipeline.py`: `parse_bank_statement_preview` |
| Clasificador          | `services/bank_classifier.py`: `classify_bank_preview_movement` |
| Duplicados (preview)  | En router `preview-multi`: fingerprint + marcar `posible_duplicado` |
| UI                    | `templates/portal_bank_pdf_to_excel.html`: Mis cuentas bancarias, una sola lista, filtros chips, detalle expandible |
| Más detalle pipeline  | `docs/BANK_PREVIEW_PIPELINE.md` |
