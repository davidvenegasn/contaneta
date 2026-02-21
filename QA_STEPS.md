# Pasos de QA para lanzamiento

Pasos exactos para probar registro, login, logout, portal (emitidas/recibidas), detalle CFDI, descarga XML/PDF y cotizaciones.

**Requisito:** App corriendo (ej. `./run_server.sh 8000` o `uvicorn app:app --reload`) y base con migraciones aplicadas.

---

## Pruebas rápidas (15 min) — copy/paste

Para el dueño: verificación mínima antes de dar por bueno el lanzamiento. Sustituir `http://127.0.0.1:8000` por tu URL si no es local.

### A. Smoke script (terminal, ~30 s)
```bash
cd /ruta/del/proyecto
./scripts/smoke.sh
```
Debe terminar con **"OK"** y código de salida 0. Si falla, no lanzar.

### B. Health (terminal)
```bash
curl -s http://127.0.0.1:8000/health
```
Esperado: `{"status":"ok","db":"ok", ...}` (o al menos `"status":"ok"`).

### C. Páginas clave (navegador)
| Qué | URL | Esperado |
|-----|-----|----------|
| Raíz | http://127.0.0.1:8000/ | Redirige a portal o login |
| Login | http://127.0.0.1:8000/login | Página "Entrar" con email/contraseña |
| Registro | http://127.0.0.1:8000/signup | Página "Crear cuenta" |
| Estado | http://127.0.0.1:8000/status | Página con status OK y DB ok |

### D. Flujo mínimo (navegador, ~10 min)
1. **Registro:** Ir a `/signup`, rellenar email, contraseña (≥8 caracteres), RFC (ej. XAXX010101000), razón social, régimen. Enviar. → Debe llevar a `/portal/home` sin `?token=` en la URL.
2. **Logout:** Clic en "Cerrar sesión" (menú usuario). → Redirige a login o raíz.
3. **Login:** Ir a `/login`, mismo email y contraseña. Enviar. → Debe llevar a `/portal/home`.
4. **Portal:** Clic en "Facturas emitidas" o "Facturas recibidas". → Listado (puede estar vacío); sin error 500.
5. **Info:** Ir a "Seguridad e información" (footer o `/portal/info`). → Página con texto de cookies y contraseña.

Si todo lo anterior pasa, el lanzamiento mínimo está verificado. Para pruebas detalladas (XML, PDF, cotizaciones, aislamiento), seguir las secciones numeradas más abajo.

---

## Pruebas UX (15 min) — pulido premium

Verificación de empty states, feedback, móvil y flujos cerrados. Base: sesión iniciada en el portal.

| # | Acción | Esperado |
|---|--------|----------|
| U1 | Ir a **Clientes** sin tener clientes. | Empty state "Aún no tienes clientes" con CTA "Crear primer cliente"; **no** alerta ni toast de error. |
| U2 | Ir a **Productos** sin productos. | Empty state "Aún no tienes productos" con "Crear primer producto"; sin error. |
| U3 | Ir a **Proveedores** sin proveedores. | Empty state "Aún no hay proveedores" con "Agregar primer proveedor" y "Ver facturas recibidas"; sin error. |
| U4 | Ir a **Cotizaciones** sin cotizaciones. | Empty state "Aún no tienes cotizaciones" con "Nueva cotización"; sin error. |
| U5 | Ir a **Facturas emitidas** (mes actual sin datos). | Empty state "No hay facturas emitidas este mes" con "Generar factura" y "Sincronizar con SAT"; **no** botón Sync en la topbar (solo en barra de la lista). |
| U6 | Ir a **Facturas recibidas** (mes sin datos). | Empty state equivalente; Sync solo en la barra de la lista. |
| U7 | En Emitidas/Recibidas, comprobar barra sobre la tabla. | Texto "Último sync: …" (o "Aún no se ha sincronizado") y botón pequeño "Sync SAT" (ghost); en móvil botón solo icono. |
| U8 | Redimensionar a **390px** (DevTools). | Sin scroll horizontal; listas en cards en emitidas/recibidas; botones y enlaces con área táctil cómoda (≈44px). |
| U9 | En **Proveedores**, si hay un proveedor, clic en "Ver facturas". | Drawer/panel se abre con scroll interno; cerrar con X o ESC; sin cortes de layout. |
| U10 | En **Cotizaciones**, "Nueva cotización". | Modal con footer fijo en móvil; botones "Cancelar", "Guardar borrador", "Enviar y obtener link" grandes y accesibles. |
| U11 | Simular fallo de carga: desconectar red y recargar **Clientes**. | Bloque "No se pudo cargar el listado" con "Reintentar"; **no** doble mensaje (toast + bloque). Al reconectar, "Reintentar" vuelve a cargar. |
| U12 | Navegar por **Inicio, Emitidas, Clientes, Productos** con el menú. | El ítem activo del sidebar se resalta (fondo y barra lateral); topbar muestra título e icono de la sección. |
| U13 | En **Generar factura** (o crear factura), añadir un concepto. | Concepto en card/fila; en móvil sin solapamientos; botón quitar concepto accesible. |
| U14 | Tras **guardar** un cliente o producto desde el modal (Home o listado). | Toast de éxito; listado o select se actualiza con el nuevo ítem. |
| U15 | Comprobar **focus** con teclado (Tab en formularios y botones). | Anillo de focus visible en inputs y botones; sin saltos raros de foco. |
| U16 | Abrir **menú usuario** (topbar) con sesión iniciada. | Bloque "Mi cuenta" con **Activación: X/4**, barra de progreso y 4 pasos clicables (Datos fiscales, Conectar SAT, Primer cliente, Primer producto). Enlaces "Completar"/"Ver" con área táctil ≥44px. Si todo está completo: "✅ Configuración completa" y botón "Ocultar". |

Si U1–U16 pasan, el pulido UX está verificado. Detalle en **UX_AUDIT_REPORT.md** y **MOBILE_CHECKLIST.md**.

---

## API: Estado de cuenta (checklist de activación)

| Aspecto | Detalle |
|--------|--------|
| **Endpoint** | `GET /api/account/status` |
| **Autenticación** | Requiere sesión o token (cookie o `?token=`). Dependencia `get_portal_issuer`; si no hay sesión válida responde **401**. |
| **Respuesta** | JSON: `issuer_ok`, `sat_ok`, `has_customer`, `has_product` (boolean), `completed` (0–4), `total` (4). |
| **Uso** | El dropdown "Mi cuenta" del portal hace `fetch` con `credentials: 'include'` al abrir y pinta el checklist de activación. |
| **Criterios** | *issuer_ok:* RFC, razón social y régimen fiscal no vacíos en `issuers`. *sat_ok:* existe fila en `sat_credentials` con `validation_ok = 1`. *has_customer:* `customer_profiles` count ≥ 1. *has_product:* `issuer_products` count ≥ 1. |

---

## 1. Registro público (/signup)

| Paso | Acción | Esperado |
|------|--------|----------|
| 1.1 | Abrir `http://127.0.0.1:8000/signup` (o `/register`, que redirige a `/signup`) | Página "Crear cuenta" con campos: correo, contraseña, RFC, razón social, régimen fiscal, CP (opcional). |
| 1.2 | Rellenar email (ej. `qa@ejemplo.com`), contraseña ≥8 caracteres, RFC (ej. `XAXX010101000`), razón social, régimen (ej. 616). Enviar. | Redirección a `http://127.0.0.1:8000/portal/home`; **sin** `?token=` en la URL. Sesión por cookie. Portal visible (menú, inicio). |
| 1.3 | Comprobar URL en barra de direcciones | Debe ser `/portal/home` sin query string. |
| 1.4 | Sin SMTP (DEV): revisar logs del servidor | Debe aparecer el enlace de verificación de correo (ej. `[DEV] Email no enviado...` con URL `/verify-email?token=...`). |

---

## 1b. Verificación por correo

| Paso | Acción | Esperado |
|------|--------|----------|
| 1b.1 | Tras registrarse, en DEV copiar el enlace de verificación de los logs (o en producción abrir el correo). | Enlace tipo `.../verify-email?token=...`. |
| 1b.2 | Abrir ese enlace en el navegador | Redirección a `/login?verified=1`. (Si el token expiró o ya se usó: `/login?verified=0`.) |

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
| 3.1 | Abrir `http://127.0.0.1:8000/login` | Página "Entrar al portal" con opción correo/teléfono, contraseña y enlace "¿Olvidaste tu contraseña?". |
| 3.2 | Introducir el mismo email y contraseña usados en registro. Enviar. | Redirección a `/portal/home`; sesión por cookie; **no** se requiere `?token=`. |
| 3.3 | Navegar a "Facturas emitidas" o "Facturas recibidas" | Listado del mes (puede estar vacío); sin errores 500. |

---

## 3b. Recuperar contraseña

| Paso | Acción | Esperado |
|------|--------|----------|
| 3b.1 | En login, clic en "¿Olvidaste tu contraseña?" o abrir `http://127.0.0.1:8000/forgot` | Página "Recuperar contraseña" con campo de correo. |
| 3b.2 | Introducir un email registrado y enviar | Mensaje "Si ese correo está registrado, recibirás un enlace...". En DEV sin SMTP: el enlace aparece en logs. |
| 3b.3 | Abrir el enlace de reset (logs en DEV o correo en producción) | Página "Nueva contraseña" con campos nueva contraseña y confirmar. |
| 3b.4 | Introducir contraseña ≥8 caracteres (y confirmar). Enviar. | Redirección a `/login?reset=1`. |
| 3b.5 | Entrar con el mismo email y la **nueva** contraseña | Redirección a `/portal/home`; login correcto. |

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
| 5.3 | Comprobar botones/enlaces "Descargar XML" y "Ver PDF" / "Descargar PDF" (todos bajo `/portal/sat/...`). | Presentes cuando hay XML; no error 404/500 al usarlos; **no** debe haber textos en blanco ni token en la URL. |

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

## 12. FIEL, validación, sync y Factura rápida (10 pasos humanos)

| Paso | Acción | Esperado |
|------|--------|----------|
| 12.1 | Ir a **Inicio** y en el bloque "Factura rápida" comprobar que existen los desplegables **Cliente** y **Producto**. | Se muestran "— Seleccionar cliente —" y "— Seleccionar producto —"; si ya hay datos, aparecen opciones. |
| 12.2 | Clic en **"+ Añadir cliente"**. | Se abre el modal "Nuevo cliente" con campos RFC, razón social, CP, régimen, email. |
| 12.3 | Rellenar RFC (ej. `XAXX010101000`), razón social, guardar. | Toast "Cliente guardado"; el nuevo cliente aparece en el desplegable Cliente y queda seleccionado. |
| 12.4 | Clic en **"+ Añadir producto"**. | Se abre el modal "Agregar producto" con descripción, Clave ProdServ, unidad, precio, IVA. |
| 12.5 | Rellenar descripción, elegir Clave ProdServ (autocompletado) y unidad (ej. E48), precio, guardar. | Toast "Producto guardado"; el nuevo producto aparece en el desplegable Producto y queda seleccionado. |
| 12.6 | Seleccionar un **Cliente** y un **Producto** en los desplegables. | El botón **"Generar factura"** se habilita. |
| 12.7 | Clic en **"Generar factura"**. | Redirección a `/portal/create?...` con datos precargados (cliente y concepto en el formulario). |
| 12.8 | Ir a **FIEL / Credenciales SAT** (desde Inicio → "Sube FIEL/CSD" o `/portal/config/sat`). | Página con estado "No configurado" o "Configurado", formulario para subir .cer, .key y contraseña. |
| 12.9 | Subir archivos **.cer** y **.key** (FIEL vigente) y contraseña; clic en **"Guardar y validar"**. | Mensaje de guardado; se ejecuta validación y se muestra resultado (✓ válido o ✗ error). Estado pasa a "Configurado" y "Última validación" con fecha y resultado. |
| 12.10 | Si la FIEL es válida: ejecutar sync SAT (script o botón según entorno, ej. `php sat_sync/sync.php` o "Sync SAT" en portal). | Sync completa sin error; en Emitidas/Recibidas aparecen o se actualizan CFDI según el período configurado. |

---

## 12b. Conectar SAT self-serve — 10 min

Flujo completo para probar que un usuario puede configurar FIEL y sincronizar sin ayuda. Requisito: PHP en PATH, `sat_sync/check_fiel.php` y dependencias Composer; opcional: cron o ejecución manual de `scripts/sat_worker.py` para procesar la cola.

| Paso | Acción | Esperado |
|------|--------|----------|
| 12b.1 | Ir a **Conectar SAT** (`/portal/config/sat`). | Página "Conectar SAT" con dropzones .cer / .key, campo contraseña, botón "Guardar y validar". Panel Estado: "No configurado" o "Configurado" y última validación. |
| 12b.2 | Subir un **.cer** y **.key** (FIEL e.firma vigente) y contraseña; clic **"Guardar y validar"**. | Archivos guardados; validación se ejecuta; Estado muestra "FIEL válida ✓" y fecha, o "Error" y mensaje legible (no stack trace). |
| 12b.3 | Pulsar **"Validar de nuevo"** (si ya hay FIEL configurada). | Respuesta inmediata (toast o recarga); Estado se actualiza con la misma o nueva validación. |
| 12b.4 | Ir a **Inicio** (`/portal/home`). | Bloque "SAT" con "Último sync: …" (o "Aún no se ha sincronizado") y botón **"Sync SAT"** (pequeño, no gigante). |
| 12b.5 | Clic en **"Sync SAT"**. | Botón pasa a "Encolando…"; luego estado "Sincronizando…" (spinner). Si el worker está corriendo, al cabo de un tiempo "Último sync" se actualiza y estado pasa a OK (o Error con mensaje). |
| 12b.6 | Ir a **Facturas emitidas** y **Facturas recibidas**. | Misma barra con "Último sync" y botón "Sync SAT"; comportamiento idéntico al de Inicio. |
| 12b.7 | Si el estado muestra **Error** (p. ej. FIEL inválida o worker no configurado). | Un solo bloque de error con mensaje claro y enlace "Ver detalle / Revalidar FIEL" a `/portal/config/sat`; no doble mensaje (toast + bloque). |
| 12b.8 | Comprobar que **worker** procesa la cola: ejecutar `APP_DB_PATH=invoicing.db python3 scripts/sat_worker.py` tras encolar desde el portal. | Jobs en `sat_jobs` con status `queued` pasan a `running` y luego `ok` o `error`; `last_error` y `finished_at` actualizados. |

Ver **SELF_SERVE_SAT.md** (guía usuario) y **OPS_RUNBOOK.md** (cron worker).

---

## Smoke script del portal

Para verificación automatizada mínima (listados, detalle, XML, PDF):

```bash
# Con app corriendo en http://127.0.0.1:8000 y token válido (ej. DEV_TOKEN o de issuer_tokens)
PORTAL_SMOKE_TOKEN=demo BASE_URL=http://127.0.0.1:8000 python scripts/smoke_portal.py
```

Requiere `requests`. Si no hay facturas en el listado, solo se comprueban listados y login; si hay al menos una, se prueba detalle y descargas XML/PDF.

### Smoke self-serve (Factura rápida + API)

Verifica portal home, API customers/products, creación de cliente y producto vía API, y que los listados devueltos por la API contienen los datos (los dropdowns de Factura rápida se llenan con esos datos):

```bash
BASE_URL=http://127.0.0.1:8000 PORTAL_SMOKE_TOKEN=demo python3 scripts/smoke_selfserve.py
```

Requiere `requests` y un token válido (ej. `DEV_TOKEN` o uno de `issuer_tokens`). La app debe estar corriendo.

---

## Checklist rápido pre-lanzamiento

- [ ] `DEV_MODE=0` en producción.
- [ ] `SESSION_SECRET` definido y fuerte.
- [ ] `COOKIE_SECURE=1` si se usa HTTPS (ver SECURITY_NOTES.md).
- [ ] Migraciones aplicadas (`schema_migrations` con versiones esperadas).
- [ ] Rate limit de login verificado (máx. 5 intentos por IP en 60 s).
- [ ] Health y scripts de backup probados.

Ver **LAUNCH_CHECKLIST.md** y **SECURITY_NOTES.md** para más detalle.
