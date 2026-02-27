# Spec: Timeouts en fetch y feedback de carga/error

**ID:** `SPEC-02`  
**Origen:** AUDIT_README.md — Estabilidad + UX, Job 4  
**Prioridad:** Alta

---

## Objetivo

Asegurar que todas las peticiones del portal que cargan datos (listados, submits) usen un helper con timeout (ej. 30 s) y que, ante timeout o error de red, se muestre un bloque de error con mensaje claro y botón "Reintentar", sin dejar la UI en "Cargando…" indefinidamente.

---

## Alcance

- Todas las pantallas del portal que cargan datos por fetch: clientes, productos, emitidas, recibidas, cotizaciones, proveedores, home (prefetch), bank preview, config SAT (status/sync), formularios que envían por fetch (guardar cliente, producto, cotización, etc.).
- Uso consistente de `portalFetchWithTimeout` o `portalFetchJSON` (definidos en `static/js/ui.js`) con `timeoutMs` (ej. 30000) y manejo de 401 (modal sesión expirada) y de timeout/error (load-error + Reintentar).
- Documentar el patrón en `docs/UI_PATTERNS.md` para futuras pantallas.

---

## Fuera de alcance

- Cambiar la implementación interna de `portalFetchWithTimeout` / `portalFetchJSON` (solo asegurar que se usen).
- Paginación server-side (spec 08).
- Unificar el comportamiento de 401 en modal (spec 03).
- Añadir timeouts a subprocess en backend (admin/sat_worker).

---

## Archivos a tocar

| Archivo / directorio | Cambio previsto |
|----------------------|-----------------|
| `templates/portal_clients.html` | Sustituir llamadas a `fetch` por `portalFetchWithTimeout`/`portalFetchJSON`; mostrar load-error con Reintentar en timeout/error. |
| `templates/portal_products.html` | Igual. |
| `templates/portal_issued.html` | Igual para la carga del listado (si no usa ya el helper). |
| `templates/portal_received.html` | Igual. |
| `templates/portal_quotations.html` | Igual. |
| `templates/portal_providers.html` | Igual. |
| `templates/portal_home.html` | Verificar prefetch y acciones que usen fetch. |
| `templates/portal_bank_pdf_to_excel.html` | Ya usa timeout; verificar mensaje de timeout y Reintentar si aplica. |
| `templates/base_portal.html` | Verificar que las llamadas a API (status, sync, etc.) usen el helper con timeout. |
| `templates/form.html` | Si hay envío por fetch, usar helper con timeout. |
| `templates/portal_create_quick_choose.html` | Verificar carga de clientes/productos. |
| `docs/UI_PATTERNS.md` | Añadir sección: "Peticiones del portal: usar portalFetchWithTimeout/portalFetchJSON; timeout 30 s; en timeout/error mostrar load-error con Reintentar." |
| Cualquier otro template que haga `fetch()` directo para datos del portal | Sustituir por el helper y manejar timeout/error. |

---

## Reglas

1. Para cargar listados o datos: usar `portalFetchWithTimeout(url, opts, timeoutMs)` o `portalFetchJSON(url, opts, { timeoutMs: 30000, retry: 0|1 })`. No usar `fetch()` directo sin timeout.
2. Timeout por defecto recomendado: 30 s (30000 ms). Para operaciones muy largas (ej. export Excel) puede ser mayor (60 s), pero siempre definido.
3. Si la petición falla por timeout o red: ocultar skeleton/contenido, mostrar el bloque `portal_load_error` (id consistente, ej. `loadErrorState`) con mensaje "La solicitud tardó demasiado. Revisa tu conexión e intenta de nuevo." (o el texto definido en UI_PATTERNS) y botón "Reintentar" que vuelva a ejecutar la carga.
4. No usar el bloque de load-error para "lista vacía"; solo para fallo de petición (timeout, red, 5xx). Lista vacía = 200 con `[]` → empty state.
5. El helper ya puede lanzar error con `type: 'timeout'` o devolver `ok: false, error: 'timeout'`; el template debe comprobar esto y mostrar load-error en lugar de empty.

---

## Criterios de aceptación

- [ ] Todas las pantallas de listado (clientes, productos, emitidas, recibidas, cotizaciones, proveedores) usan `portalFetchWithTimeout` o `portalFetchJSON` con timeout (ej. 30 s) para la carga inicial de datos.
- [ ] Al superar el timeout, se muestra el bloque de error con mensaje claro y botón "Reintentar"; al pulsar Reintentar se vuelve a lanzar la carga.
- [ ] Ninguna pantalla queda en "Cargando…" o skeleton de forma indefinida cuando la petición falla o hace timeout (en un tiempo razonable, ej. 35 s).
- [ ] Los submits (guardar cliente, producto, cotización, etc.) que usen fetch tienen timeout y manejo de error (toast o mensaje); no se queda el botón en "Guardando…" sin feedback.
- [ ] `docs/UI_PATTERNS.md` documenta el patrón: usar helper con timeout, load-error para timeout/error, empty para lista vacía.
- [ ] Tras implementar, ejecutar `scripts/audit_coverage.py` y comprobar que no queden "fetch sin portalFetchWithTimeout" en los archivos del portal que cargan datos.

---

## Cómo probarlo manualmente

1. **Timeout:** En DevTools → Network, throttling "Slow 3G" o simular offline tras iniciar la carga. En una lista (ej. clientes), esperar a que pase el timeout (30 s). Debe aparecer el bloque de error con "Reintentar". Pulsar Reintentar y, con red normal, debe cargar.
2. **Error de red:** Cargar una lista, antes de que responda cortar la red o detener el servidor. Debe aparecer load-error y Reintentar.
3. **Lista vacía:** Llamar a una API que devuelva 200 con `[]`. No debe mostrarse load-error; debe mostrarse empty state.
4. **Guardar:** En guardar cliente/producto, simular timeout o error. Debe aparecer toast o mensaje de error y el formulario no debe quedar bloqueado.
5. **Revisar cada pantalla:** Clientess, Productos, Emitidas, Recibidas, Cotizaciones, Proveedores, Home, Bank PDF, Config SAT — verificar que en todas haya timeout y feedback de error con Reintentar donde aplique.

---

## Referencias

- AUDIT_README.md — Sección 1.3 (Timeouts), Lista priorizada Alta, Job 4.
- docs/UI_PATTERNS.md — Empty vs load-error.
- static/js/ui.js — `portalFetchWithTimeout`, `portalFetchJSON`.
- templates/portal/_ui_components.html — `portal_load_error`.
