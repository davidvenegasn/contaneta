# Auditoría del portal — Mejoras de funcionamiento, continuidad y diseño

**Objetivo de esta auditoría:** Detectar puntos mejorables en el portal (funcionamiento, continuidad para que no caiga el servicio, y diseño) y dejar listas **tareas largas** que puedas asignar para implementar las mejoras.

**Alcance:** Portal de usuario (`/portal/*`), flujos de registro/login/onboarding, listados (clientes, productos, emitidas, recibidas, cotizaciones, proveedores), factura rápida, configuración SAT, descargas XML/PDF y experiencia móvil.

---

## Resumen ejecutivo (léeme primero)

- **Funcionamiento:** El portal cumple los flujos principales (inicio, listados, factura, SAT, descargas). Hay mejoras en validación en backend, consistencia de mensajes de error y feedback en acciones (guardar, eliminar, sync).
- **Continuidad:** Hay riesgos de caída o mal comportamiento: excepciones convertidas en 400 con HTML crudo, falta de timeouts en muchas peticiones fetch, sesión que puede expirar en medio de formularios largos sin mensaje claro. La base (SQLite, migraciones, cron SAT) está razonablemente cubierta.
- **Diseño:** Hay empty states y estilos móviles (44px, breakpoints). Faltan consistencia en espaciados/tonos entre páginas, algunos estados de carga poco claros y oportunidades de simplificar navegación y jerarquía visual.

Al final del documento se listan **tareas largas** agrupadas por tema para que puedas implementar las mejoras en bloques.

---

## 1. FUNCIONAMIENTO

### 1.1 Rutas y flujos

- **Rutas del portal:** Todas bajo `routers/portal.py` con prefijo `/portal`. Inicio (`/portal/home`), listados (emitidas, recibidas, clientes, productos, proveedores, cotizaciones), configuración SAT (`/portal/config/sat`), descargas XML/PDF (`/portal/sat/xml/{uuid}`, `/portal/sat/pdf/{uuid}`), factura (`/portal/create`, `/portal/create/quick`).
- **Dependencia de sesión:** `get_portal_issuer` (deps) exige cookie o `?token=`. Sin sesión → 401 y redirect a `/login` para HTML.
- **Flujos críticos:** Registro → confirmar perfil → onboarding → home; home → factura rápida o crear factura; emitidas/recibidas → detalle CFDI → descargar XML/PDF; config SAT → subir FIEL → validar → sync.

**Hallazgos:**

| # | Hallazgo | Dónde | Severidad |
|---|----------|--------|-----------|
| F1 | Algunas rutas del portal capturan `Exception` y devuelven `HTMLResponse(..., status_code=400)` con el mensaje de la excepción, mezclando errores de cliente (400) con fallos de servidor (500). | `routers/portal.py` (y posiblemente otros) | Media |
| F2 | Falta validación explícita de límites (p. ej. `limit`/`offset`) en varias APIs de listados; si no hay tope, una respuesta muy grande puede degradar rendimiento o tiempo de respuesta. | `routers/api.py`, endpoints de listas | Media |
| F3 | El botón "Sync SAT" encola jobs en `sat_jobs` pero el procesamiento real lo hace `sat_worker.py` o el cron PHP; si el cron no está configurado, el usuario ve "Sincronización iniciada" pero los datos no bajan. No hay mensaje en UI que indique "puede tardar unos minutos" o "revisa que el cron esté activo". | Portal home, barra sync, `portal_sat_sync` | Baja |
| F4 | En "Agregar producto" y "Agregar cliente" la búsqueda de catálogo ProdServ/Unidad depende de `/api/catalogs/prodserv` y similares; si la API falla o tarda, el usuario solo ve lista vacía sin mensaje ("no hay resultados" vs "error de red"). | `portal_products.html`, `portal_clients.html`, form | Baja |
| F5 | Descargas XML/PDF devuelven 402 cuando el plan no permite sync/timbrado; el mensaje redirige a `/pricing`. Conviene asegurar que la página de plan/pricing exista y esté enlazada desde el menú. | `routers/portal.py`, templates | Baja |

### 1.2 Formularios y validación

- **Front:** Validación HTML5 y JS en formularios (descripción, clave ProdServ, precio, etc.). Toasts para éxito/error.
- **Back:** Validación en routers con `Form()`/`Body()`; algunos endpoints devuelven 400 con `detail` en JSON.

**Hallazgos:**

| # | Hallazgo | Dónde | Severidad |
|---|----------|--------|-----------|
| F6 | Validación duplicada o inconsistente entre front y back: por ejemplo, "Clave ProdServ obligatoria" en front puede no coincidir con el mensaje del backend si falla el create. | Templates (portal_products, portal_clients), `routers/api.py` | Baja |
| F7 | En formulario de factura (form.html) hay muchos campos; si el usuario tarda mucho, la sesión puede expirar y al enviar recibirá 401. Existe modal "Sesión expirada" en base_portal; verificar que se dispare en todos los submits de formularios largos. | `form.html`, `ui.js`, handlers 401 | Media |

### 1.3 Listados y carga de datos

- **Patrón:** Cada listado (clientes, productos, emitidas, recibidas, cotizaciones, proveedores) hace `fetch` a una API (o a `/portal/...` con JSON), muestra skeleton o "Cargando…", luego tabla o empty state o bloque de error ("No pudimos cargar esto ahora" + Reintentar).
- **Helper:** `window.uiFetchJSON` (definido en `ui.js`) se usa en la mayoría; si no está disponible en el momento de la primera carga (script order), se mostraba "Helper no disponible" — ya se corrigió cargando `ui.js` antes del bloque content.

**Hallazgos:**

| # | Hallazgo | Dónde | Severidad |
|---|----------|--------|-----------|
| F8 | En algunas listas no hay timeout en el `fetch`; si la API no responde, la UI se queda en "Cargando…" hasta que el navegador corte. Añadir `AbortController` + timeout (p. ej. 30 s) y mostrar "Revisa tu conexión" al vencer. | Templates con loadData() (portal_clients, portal_products, portal_issued, etc.) | Media |
| F9 | Paginación en front (clientes, productos, proveedores) es solo en memoria (ROWS_PAGE_LIMIT 200); si la API devuelve más de 200, no se ven. No hay paginación server-side en la API. | `routers/api.py` (customers, products, providers), JS de listados | Baja |

---

## 2. CONTINUIDAD (EVITAR QUE CAIGA EL PORTAL)

### 2.1 Manejo de errores en backend

- **Global:** `app.py` tiene handlers para 404, 500, HTTPException. 401/403 con `Accept: text/html` → redirect `/login`. API devuelve JSON con `detail` o cuerpo unificado.
- **Portal:** Varias rutas usan `try/except` y devuelven HTML con mensaje de la excepción y status 400, lo que contamina el código de estado.

**Hallazgos:**

| # | Hallazgo | Dónde | Severidad |
|---|----------|--------|-----------|
| C1 | Unificar manejo de errores en rutas del portal: no devolver 400 para fallos de servidor (BD, subprocess, etc.). Usar `HTTPException(500, detail="...")` o dejar que la excepción suba al handler global. Revisar todas las rutas que hacen `except Exception` y responden con HTML. | `routers/portal.py`, otros routers que sirven portal | Alta |
| C2 | Errores en generación de PDF (reportlab, archivo no encontrado) devuelven 500 con HTML; está bien, pero el mensaje no debe exponer rutas internas ni stack traces en producción. | `/portal/sat/pdf/{uuid}` | Media |

### 2.2 Sesión y autenticación

- **Cookie:** Sesión manejada por `services/session.py`; expira según configuración. Sin cookie válida → 401 y redirect a login.
- **Modal sesión expirada:** En `base_portal.html` hay modal para 401; `ui.js` puede interceptar respuestas 401 y mostrarlo.

**Hallazgos:**

| # | Hallazgo | Dónde | Severidad |
|---|----------|--------|-----------|
| C3 | Comprobar que en todas las peticiones fetch del portal que puedan devolver 401 (APIs de listados, create, delete, sync, etc.) se muestre el modal "Sesión expirada" y se cierren overlays/drawers abiertos, sin dejar la UI en estado inconsistente. | `ui.js`, templates que llaman uiFetchJSON o fetch | Media |
| C4 | Rate limit: existe en login y en FIEL upload/validate; verificar que no se pueda abusar de endpoints costosos (p. ej. sync SAT, creación masiva) sin límite. | `routers/portal.py`, `routers/auth.py`, servicios rate_limit | Baja |

### 2.3 Base de datos y concurrencia

- **SQLite:** `database.py` usa `busy_timeout=5000` y `journal_mode=WAL`. Cada request abre/cierra conexión.
- **SAT sync:** Cron (PHP) y opcionalmente `sat_worker.py` acceden a la misma DB; el worker usa WAL y busy_timeout.

**Hallazgos:**

| # | Hallazgo | Dónde | Severidad |
|---|----------|--------|-----------|
| C5 | Asegurar que todas las rutas que escriben en la BD usen la misma función de conexión (`database.db()` o la que aplique) con `busy_timeout` y WAL, para evitar "database is locked" bajo carga. | `database.py`, cualquier código que abra SQLite sin pasar por db() | Media |
| C6 | Migraciones se aplican al arranque; si una migración falla, la app puede no levantar. Documentar rollback y que /health indique migrations_applied y versión. | `migrations_runner.py`, `app.py`, documentación | Baja |

### 2.4 Dependencias externas

- **PHP (sat_sync):** Necesario para FIEL y descarga SAT. Si PHP no está en PATH o falla `check_fiel.php`, la validación FIEL devuelve error; el resto del portal sigue funcionando.
- **Cron SAT:** Si no está configurado, los datos de emitidas/recibidas no se actualizan solos; el usuario puede hacer "Sync" pero el worker debe estar corriendo (o el cron PHP).

**Hallazgos:**

| # | Hallazgo | Dónde | Severidad |
|---|----------|--------|-----------|
| C7 | En entorno de producción, documentar claramente: 1) PHP en PATH o variable, 2) crontab para cron_sat_sync.sh (o sat_worker.py si se usa cola), 3) qué hacer si "Sync" nunca termina (revisar sat_jobs, logs). | OPS_RUNBOOK, LAUNCH_CHECKLIST, README | Baja |

---

## 3. DISEÑO Y UX

### 3.1 Consistencia visual

- **Estilos:** `form.css`, `portal_tokens.css`, `components.css`, `portal.css` cargados en base_portal. Variables en portal_tokens (colores, espaciado, radios).
- **Componentes:** Botones (btn, btn-primary, btn-ghost), cards, modales, empty states, toasts. Algunas páginas definen estilos inline en el propio template (portal_products, portal_home).

**Hallazgos:**

| # | Hallazgo | Dónde | Severidad |
|---|----------|--------|-----------|
| D1 | Reducir estilos inline en templates (portal_products, portal_home, etc.) y mover a portal.css o components.css con clases semánticas, para mantener una sola fuente de verdad y facilitar temas (p. ej. noche). | Templates, static/css/portal.css | Baja |
| D2 | Algunos títulos de sección usan `section-title` y otros variantes; breadcrumbs y topbar no siempre tienen el mismo espaciado entre páginas. Revisar guía de espaciado (--space-*) y aplicarla de forma uniforme. | base_portal, portal_*.html, portal.css | Baja |
| D3 | Empty states: el texto y la ilustración/icono son consistentes entre clientes, productos, proveedores, cotizaciones; emitidas/recibidas tienen CTA "Crear factura" o "Ir a recibidas". Revisar que en todas las listas el empty state tenga un CTA claro. | Templates con empty-state | Baja |

### 3.2 Estados de carga y feedback

- **Carga inicial:** Skeleton en tabla (filas con skeleton) o texto "Cargando…"; al recibir datos se pinta la tabla o el empty state o el bloque de error.
- **Acciones:** Guardar, eliminar, sync: se usan `uiSetButtonLoading` y toasts.

**Hallazgos:**

| # | Hallazgo | Dónde | Severidad |
|---|----------|--------|-----------|
| D4 | En listados, el paso de "Cargando…" a contenido puede ser brusco; en conexiones lentas el usuario no sabe si está cargando o colgado. Considerar skeleton más visible o mensaje "Cargando…" con animación. | portal_clients, portal_products, portal_issued, portal_received | Baja |
| D5 | Tras "Guardar" en cliente/producto/cotización, a veces se muestra toast y se cierra el modal; en otros flujos hay overlay de éxito. Unificar: toast + cierre de modal, o overlay con acciones, pero no mezclar sin criterio. | Varios formularios del portal | Baja |
| D6 | Error en guardar: a veces solo toast, a veces toast + mensaje en el formulario. Definir patrón único (p. ej. toast para error de red/servidor, mensaje bajo el botón para validación). | Formularios en portal_*.html | Baja |

### 3.3 Navegación y jerarquía

- **Sidebar:** Agrupación por secciones (Principal, Facturas, Catálogos, Otros). En móvil es drawer.
- **Breadcrumb:** Inicio › [página]. Falta en algunas vistas (p. ej. detalle CFDI tiene "Volver al listado" pero no breadcrumb completo).

**Hallazgos:**

| # | Hallazgo | Dónde | Severidad |
|---|----------|--------|-----------|
| D7 | En detalle de CFDI (emitido/recibido) y en detalle de cotización, añadir breadcrumb consistente (Inicio › Emitidas › [UUID] o Inicio › Cotizaciones › [id]) para no depender solo del botón "Volver". | portal_cfdi_detail.html, quote_detail.html | Baja |
| D8 | "Factura rápida" aparece en home y en menú; "Genera factura" puede llevar a /portal/create o a elegir cliente/producto. Unificar nombres y rutas para no confundir (rápida = elegir cliente+producto; nueva = formulario completo). | Navegación, enlaces en home | Baja |

### 3.4 Móvil y accesibilidad

- **Breakpoints:** 390px, 480px, 768px, 900px en portal.css y form.css. Tablas con scroll horizontal en móvil; botones y targets mínimos 44px.
- **Reduced motion:** Hay bloques `@media (prefers-reduced-motion: reduce)` para animaciones.
- **ARIA:** Sidebar, modales y menús tienen `aria-hidden`, `aria-expanded`, `role="dialog"` donde aplica.

**Hallazgos:**

| # | Hallazgo | Dónde | Severidad |
|---|----------|--------|-----------|
| D9 | En 390px algunas tablas (clientes, productos, proveedores) dependen de scroll horizontal; según BACKLOG ya se consideró vista en cards. Valorar si implementar vista en cards para móvil para evitar scroll horizontal. | portal.css, portal_clients/products/providers | Baja |
| D10 | Focus trap en modales y drawers: al abrir, el foco debe ir al primer elemento focusable y no salir del modal hasta cerrar. Verificar que en modal de factura rápida, drawer CFDI y drawer proveedores se cumpla. | base_portal, ui.js, templates con modales | Media |
| D11 | Mensajes de error y toasts deben ser anunciados por lectores de pantalla (aria-live o role="alert"). Revisar que #toastStack y bloques de error tengan atributos adecuados. | base_portal.html, static/css | Baja |

---

## 4. TAREAS LARGAS SUGERIDAS PARA IMPLEMENTAR

A continuación se agrupan mejoras en **tareas largas** que puedes asignar como bloques de trabajo. Cada una puede llevarte varias horas o días según el alcance que des.

---

### Tarea 1 — Unificar manejo de errores en el portal (continuidad)

**Objetivo:** Evitar que errores de servidor se devuelvan como 400 y que el usuario vea mensajes crudos de excepción.

**Incluye:**

- Revisar todas las rutas en `routers/portal.py` (y cualquier otra que sirva HTML del portal) que usen `try/except Exception` y devuelvan `HTMLResponse` con status 400.
- Reemplazar por: o bien `HTTPException(500, detail="...")` con mensaje genérico amigable, o dejar que la excepción suba al handler global de 500.
- Asegurar que en producción el handler de 500 no muestre stack trace ni rutas internas en el HTML.
- Opcional: logging estructurado (request_id, ruta, status) para cada 5xx.

**Criterios de aceptación:** Ninguna ruta del portal devuelve 400 con cuerpo de excepción; 5xx con mensaje genérico; logs útiles para diagnóstico.

---

### Tarea 2 — Timeouts y feedback en peticiones del portal (funcionamiento + continuidad)

**Objetivo:** Que las listas y acciones no se queden colgadas indefinidamente y el usuario reciba un mensaje claro si hay fallo de red o tiempo de espera.

**Incluye:**

- Añadir `AbortController` + timeout (p. ej. 30 s) en todas las llamadas `fetch` o `uiFetchJSON` que cargan listados (clientes, productos, emitidas, recibidas, cotizaciones, proveedores).
- Al superar el timeout: abortar la petición, mostrar el bloque de error "No pudimos cargar esto ahora" con mensaje tipo "La solicitud tardó demasiado. Revisa tu conexión e intenta de nuevo." y botón Reintentar.
- Revisar que en guardar (cliente, producto, cotización, factura) haya también timeout o al menos mensaje claro si la petición falla por red.
- Documentar en un comentario o en un helper único (`portalFetchWithTimeout`) el patrón a seguir para nuevas pantallas.

**Criterios de aceptación:** Ningún listado queda en "Cargando…" para siempre; timeout 30 s con mensaje y Reintentar; mismo patrón en todas las listas.

---

### Tarea 3 — Experiencia de sesión expirada en todo el portal (continuidad)

**Objetivo:** Que en cualquier flujo (formulario largo, listado, descarga) un 401 muestre el modal "Sesión expirada" y se cierre cualquier overlay/drawer abierto.

**Incluye:**

- Revisar que `uiFetchJSON` (o el helper que use cada página) intercepte 401 y llame a la función que muestra el modal de sesión expirada (y cierre overlays).
- Aplicar en: listados (clientes, productos, emitidas, recibidas, cotizaciones, proveedores), creación/edición (cliente, producto, cotización), factura (form.html), sync SAT, descargas XML/PDF si se hacen por fetch.
- Asegurar que el modal tenga botón "Iniciar sesión" que lleve a `/login` y que al cerrar el modal no quede la UI en estado inconsistente (p. ej. drawer abierto con datos vacíos).

**Criterios de aceptación:** Cualquier 401 en una petición del portal muestra el modal y cierra overlays; un solo lugar donde se define el comportamiento del 401.

---

### Tarea 4 — Consistencia de empty states, errores y mensajes de éxito (diseño + funcionamiento)

**Objetivo:** Un solo patrón para "lista vacía", "error de carga" y "acción completada".

**Incluye:**

- Empty state: en todas las listas, mismo estilo (icono, título, descripción, CTA). Revisar que el texto no diga "error" cuando la API devolvió 200 y lista vacía.
- Error de carga: solo un bloque "No pudimos cargar esto ahora" con Reintentar; no duplicar con toast (según BACKLOG B6).
- Éxito: definir si tras guardar (cliente/producto/cotización) se usa solo toast o toast + overlay; aplicar el mismo criterio en todos los formularios.
- Mensajes de validación: mismo tono y lugar (bajo campo o bajo botón) en todos los formularios.

**Criterios de aceptación:** Documento corto o comentario en base_portal con las reglas; todas las pantallas del portal las cumplen.

---

### Tarea 5 — Mejoras de diseño visual y espaciado (diseño)

**Objetivo:** Reducir estilos inline y unificar espaciados y jerarquía.

**Incluye:**

- Mover estilos inline de portal_products, portal_home y otros templates a clases en portal.css o components.css.
- Revisar uso de `--space-*` y márgenes/paddings en cards, títulos y listas para que sean coherentes entre páginas.
- Añadir breadcrumb completo en detalle CFDI y detalle cotización (Inicio › Emitidas › [UUID]).
- Revisar nombres de enlaces ("Factura rápida" vs "Genera factura") y que lleven a la pantalla esperada.

**Criterios de aceptación:** Cero o mínimo estilos inline en templates del portal; espaciado uniforme; breadcrumbs en detalle CFDI y cotización.

---

### Tarea 6 — Accesibilidad en modales y drawers (diseño)

**Objetivo:** Focus trap y cierre con Escape en todos los modales/drawers; anuncio de errores para lectores de pantalla.

**Incluye:**

- Al abrir modal (factura rápida, agregar producto, agregar cliente, ProdServ, etc.) y drawers (CFDI, proveedores): mover foco al primer elemento focusable y atrapar el foco dentro hasta cerrar (tecla Tab no salga del modal).
- Cerrar con Escape en todos los modales y drawers.
- Revisar que los toasts y bloques de error tengan `aria-live="polite"` o `role="alert"` según el caso.
- Comprobar que botones e iconos tengan `aria-label` donde el texto no sea visible.

**Criterios de aceptación:** Lista de modales/drawers con focus trap y ESC; toasts y errores anunciados; sin regresiones en uso con teclado.

---

### Tarea 7 — Sync SAT y documentación para el usuario (funcionamiento + continuidad)

**Objetivo:** Que el usuario entienda que el sync puede tardar y qué hacer si no ve datos.

**Incluye:**

- En la UI (home o barra de sync): texto corto tipo "La sincronización puede tardar unos minutos. Si no ves datos, vuelve a intentar más tarde o revisa tu configuración SAT."
- En documentación (README o SELF_SERVE_SAT): pasos claros de configuración de cron (cron_sat_sync.sh o sat_worker.py) y qué esperar cuando se pulsa "Sync".
- Opcional: en /health o /status mostrar un indicador "último sync exitoso por issuer" para soporte.

**Criterios de aceptación:** Mensaje visible en la UI del sync; documentación actualizada; opcional health con info de sync.

---

### Tarea 8 — Paginación y límites en APIs de listados (funcionamiento + continuidad)

**Objetivo:** Evitar respuestas enormes que degraden rendimiento.

**Incluye:**

- Revisar endpoints de listados (clientes, productos, cotizaciones, proveedores, emitidas, recibidas): añadir parámetros `limit` y `offset` (o `page`) con límite máximo (p. ej. 500 por página).
- En el front, si se usa paginación en servidor: botones "Anterior/Siguiente" que pidan la siguiente página; si se mantiene paginación en memoria, al menos limitar la primera carga (p. ej. 200 ítems) y avisar "Mostrando los primeros 200" si hay más.

**Criterios de aceptación:** Ninguna API de listado devuelve más de X ítems sin límite; documentar el límite; front coherente con la API.

---

## 5. PRIORIZACIÓN SUGERIDA

Para maximizar impacto con el menor riesgo:

1. **Primero (continuidad):** Tarea 1 (errores en backend), Tarea 3 (sesión expirada).
2. **Segundo (funcionamiento):** Tarea 2 (timeouts), Tarea 4 (empty states y mensajes).
3. **Tercero (diseño):** Tarea 5 (estilos y breadcrumbs), Tarea 6 (accesibilidad).
4. **Cuarto (operación y claridad):** Tarea 7 (sync y documentación), Tarea 8 (paginación y límites).

---

## 6. REFERENCIAS EN EL PROYECTO

- **Rutas y flujos:** `routers/portal.py`, `routers/deps.py` (get_portal_issuer).
- **Manejo de errores:** `app.py` (handlers 404, 500, HTTPException).
- **Frontend global:** `templates/base_portal.html`, `static/js/ui.js`, `static/css/portal.css`.
- **Listados y empty states:** `templates/portal_clients.html`, `portal_products.html`, `portal_issued.html`, `portal_received.html`, `portal_quotations.html`, `portal_providers.html`.
- **Backlog y riesgos:** `BACKLOG.md`, `AUDIT_REPORT.md`, `OPS_RUNBOOK.md`, `LAUNCH_CHECKLIST.md`.

Si quieres, puedo bajar alguna tarea a pasos más granulares (por archivo o por checklist) para implementación directa.
