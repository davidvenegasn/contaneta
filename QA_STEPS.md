# Pasos de QA para lanzamiento

Pasos exactos para probar registro, login, logout, portal (emitidas/recibidas), detalle CFDI, descarga XML/PDF y cotizaciones.

**Requisito:** App corriendo (ej. `uvicorn app:app --reload`) y base con migraciones aplicadas.

---

## 1. Registro

| Paso | Acción | Esperado |
|------|--------|----------|
| 1.1 | Abrir `http://127.0.0.1:8000/register` | Página "Crear cuenta" con campos: correo, contraseña, RFC, razón social, régimen fiscal, CP (opcional). |
| 1.2 | Rellenar email (ej. `qa@ejemplo.com`), contraseña ≥8 caracteres, RFC (ej. `XAXX010101000`), razón social, régimen (ej. 616). Enviar. | Redirección a `http://127.0.0.1:8000/portal/home`; **sin** `?token=` en la URL. Portal visible (menú, inicio). |
| 1.3 | Comprobar URL en barra de direcciones | Debe ser `/portal/home` sin query string. |

---

## 2. Logout

| Paso | Acción | Esperado |
|------|--------|----------|
| 2.1 | Desde el portal, usar enlace/botón de cerrar sesión o ir a `http://127.0.0.1:8000/logout` | Redirección a `/` (o `/login`). Cookie de sesión eliminada. |
| 2.2 | Intentar abrir `http://127.0.0.1:8000/portal/home` | Redirección a `/login` (si DEV_MODE=0). |

---

## 3. Login con email

| Paso | Acción | Esperado |
|------|--------|----------|
| 3.1 | Abrir `http://127.0.0.1:8000/login` | Página "Entrar al portal" con opción correo/teléfono y contraseña. |
| 3.2 | Introducir el mismo email y contraseña usados en registro. Enviar. | Redirección a `/portal/home`; sesión por cookie; **no** se requiere `?token=`. |
| 3.3 | Navegar a "Facturas emitidas" o "Facturas recibidas" | Listado del mes (puede estar vacío); sin errores 500. |

---

## 4. Portal: facturas emitidas y recibidas

| Paso | Acción | Esperado |
|------|--------|----------|
| 4.1 | Ir a `http://127.0.0.1:8000/portal/invoices/issued` (o desde menú "Facturas emitidas") | Página con selector de mes y tabla de facturas emitidas (o estado vacío). |
| 4.2 | Ir a `http://127.0.0.1:8000/portal/invoices/received` | Página con selector de mes y tabla de facturas recibidas (o estado vacío). |
| 4.3 | Si hay al menos una factura con XML: comprobar que cada fila muestra UUID, total, estatus y botones "Ver XML" / "Ver PDF" cuando aplique. | Sin errores; botones visibles donde `xml_path` existe. |

---

## 5. Detalle CFDI

| Paso | Acción | Esperado |
|------|--------|----------|
| 5.1 | Desde emitidas o recibidas, clic en un UUID (o enlace "Ver detalle") que lleve a detalle del CFDI. | URL tipo `/portal/cfdi/issued/{uuid}` o `/portal/cfdi/received/{uuid}`. |
| 5.2 | Comprobar que la página muestra: fecha, receptor/emisor, concepto, total, IVA, estatus. | Datos coherentes con la fila del listado. |
| 5.3 | Comprobar botones/enlaces "Descargar XML" y "Ver PDF" / "Descargar PDF". | Presentes cuando hay XML; no error 404/500 al usarlos. |

---

## 6. Descargar XML

| Paso | Acción | Esperado |
|------|--------|----------|
| 6.1 | Con sesión activa, abrir directamente `http://127.0.0.1:8000/portal/sat/xml/{uuid}` sustituyendo `{uuid}` por un UUID real del issuer actual. | Descarga o visualización del XML; Content-Type `application/xml`. |
| 6.2 | Desde el listado de emitidas/recibidas, clic en "Ver XML" o "Descargar XML" de una fila. | Mismo resultado: XML correcto para ese UUID. |
| 6.3 | (Opcional) Con otro usuario/issuer, intentar el mismo UUID del paso 6.1. | 404 "XML no encontrado" o "no encontrado"; no se sirve el XML de otro issuer. |

---

## 7. Generar / descargar PDF (CFDI)

| Paso | Acción | Esperado |
|------|--------|----------|
| 7.1 | En listado o detalle, clic en "Ver PDF" (o "Descargar PDF") de un CFDI que tenga XML. | Se genera el PDF (ReportLab) y se muestra en navegador o se descarga. |
| 7.2 | Abrir `http://127.0.0.1:8000/portal/sat/pdf/{uuid}` con un UUID válido del issuer. | PDF del CFDI (inline o descarga según `dl`). |
| 7.3 | Abrir `http://127.0.0.1:8000/portal/sat/pdf/{uuid}?dl=1` | Descarga del PDF (Content-Disposition: attachment). |

---

## 8. Cotizaciones (si aplica)

| Paso | Acción | Esperado |
|------|--------|----------|
| 8.1 | Ir a Cotizaciones desde el menú (`/portal/cotizaciones` o equivalente). | Listado de cotizaciones del issuer. |
| 8.2 | Crear una cotización de prueba (cliente, conceptos, guardar). | Se guarda y aparece en el listado. |
| 8.3 | Abrir una cotización guardada (detalle). | Página con datos, totales y sección "Vista previa PDF". |
| 8.4 | Clic en "Vista previa PDF" o "Descargar PDF" en detalle de cotización. | Se muestra o descarga el PDF de la cotización (ReportLab). |
| 8.5 | Abrir `http://127.0.0.1:8000/portal/quotations/{id}/pdf` (con `id` de una cotización del issuer). | PDF inline; sin token en URL si la sesión cookie es válida. |

---

## 9. Token legacy (acceso por enlace)

| Paso | Acción | Esperado |
|------|--------|----------|
| 9.1 | Obtener un token válido de la tabla `issuer_tokens` (issuer activo). | Ej. `SELECT token FROM issuer_tokens WHERE active=1 LIMIT 1;` |
| 9.2 | Abrir `http://127.0.0.1:8000/login?token=EL_TOKEN` | Redirección a `/portal/home` **sin** `?token=` en la URL; cookie de sesión establecida. |
| 9.3 | Navegar por portal (emitidas, recibidas, descargas). | Mismo comportamiento que con login por email; todo por cookie. |

---

## 10. Aislamiento por issuer y auditoría

| Paso | Acción | Esperado |
|------|--------|----------|
| 10.1 | Con usuario A (issuer 1), anotar un UUID de una factura emitida. Cerrar sesión. Iniciar sesión con usuario B (issuer 2). | - |
| 10.2 | Abrir `http://127.0.0.1:8000/portal/sat/xml/{uuid_de_A}`. | 404 o "no encontrado"; no se sirve el XML del issuer A. |
| 10.3 | Tras login, logout y una descarga XML, consultar: `SELECT action, user_id, issuer_id, details, created_at FROM audit_log ORDER BY id DESC LIMIT 10;` | Filas con `login`, `logout`, `download_xml` (y opcionalmente `download_pdf`, `quotation_pdf`) con IDs correctos. |

---

## 11. Health y backups

| Paso | Acción | Esperado |
|------|--------|----------|
| 11.1 | `curl -s http://127.0.0.1:8000/health` | `{"status":"ok","db":"ok"}` (o `"degraded"` si DB no accesible). |
| 11.2 | Ejecutar `./scripts/backup_db.sh` | Se crea `backup/invoicing_YYYYMMDD_HHMMSS.db`. |
| 11.3 | Si existe directorio `storage`, ejecutar `./scripts/backup_storage_xml.sh` | Se crea `backup/storage_YYYYMMDD_HHMMSS`. |

---

## Checklist rápido pre-lanzamiento

- [ ] `DEV_MODE=0` en producción.
- [ ] `SESSION_SECRET` definido y fuerte.
- [ ] `COOKIE_SECURE=1` si se usa HTTPS (ver SECURITY_NOTES.md).
- [ ] Migraciones aplicadas (`schema_migrations` con versiones esperadas).
- [ ] Rate limit de login verificado (máx. 5 intentos por IP en 60 s).
- [ ] Health y scripts de backup probados.

Ver **LAUNCH_CHECKLIST.md** y **SECURITY_NOTES.md** para más detalle.
