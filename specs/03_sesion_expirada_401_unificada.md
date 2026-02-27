# Spec: Sesión expirada (401) unificada

**ID:** `SPEC-03`  
**Origen:** AUDIT_README.md — Funcionamiento, Job 5  
**Prioridad:** Media

---

## Objetivo

Unificar el comportamiento ante respuesta 401 en todas las pantallas y formularios del portal: mostrar el modal "Sesión expirada", cerrar cualquier overlay/drawer abierto y ofrecer el enlace "Iniciar sesión". Un solo lugar donde se define este comportamiento para no duplicar lógica ni dejar flujos sin cubrir.

---

## Alcance

- Todas las peticiones del portal que puedan recibir 401: listados (clientes, productos, emitidas, recibidas, cotizaciones, proveedores), formularios (guardar cliente, producto, cotización), factura rápida (home), sync SAT, config SAT, bank preview (preview-json, reclassify, export), y cualquier otra llamada fetch que use la sesión.
- El helper de fetch (`portalFetchWithTimeout` / `portalFetchJSON` en `static/js/ui.js`) debe interceptar 401 y llamar a una función global que muestre el modal y cierre overlays (ej. `showSessionExpiredModal`, `uiCloseAllOverlays`).
- Modal de sesión expirada en `templates/base_portal.html`: asegurar que esté presente y que el botón lleve a `/login`.
- Formularios que envían por POST full-page (form factura, login, etc.): si el servidor devuelve 401, el navegador puede redirigir a login; no es obligatorio modal en ese caso, pero sí que no quede la UI en estado inconsistente.

---

## Fuera de alcance

- Cambiar la lógica de expiración de sesión en backend (cookie, TTL).
- Cambiar las rutas que devuelven 401 (eso ya lo hace `get_portal_issuer` y similares).
- Implementar refresh de token o "mantener sesión activa".
- Afectar a rutas que no requieren sesión (públicas, login, pricing).

---

## Archivos a tocar

| Archivo / directorio | Cambio previsto |
|----------------------|-----------------|
| `static/js/ui.js` | Asegurar que en la respuesta 401 se llame a la función que muestra el modal de sesión expirada y, si existe, `uiCloseAllOverlays` (o equivalente). Documentar en comentario. |
| `templates/base_portal.html` | Verificar que el modal de sesión expirada exista, tenga id estable (ej. para poder mostrarlo desde JS), botón "Iniciar sesión" con href="/login", y que al mostrarse se cierren overlays/drawers (llamar a `uiCloseAllOverlays` si existe). |
| Templates que hagan fetch propio (portal_clients, portal_products, portal_issued, portal_received, portal_quotations, portal_providers, portal_home, portal_bank_pdf_to_excel, form.html si aplica) | Si manejan 401 de forma distinta (ej. redirect manual), unificar: en 401 llamar a la misma función global que muestra el modal y cierra overlays. No duplicar lógica de "si 401 entonces redirect" en cada template; centralizar en el helper de fetch o en una sola función `showSessionExpiredModal()`. |

---

## Reglas

1. Toda petición fetch del portal que reciba 401 debe terminar en el mismo comportamiento: mostrar modal "Sesión expirada" (o el texto definido en base_portal) y cerrar overlays/drawers.
2. No redirigir automáticamente a `/login` desde JS en 401 si se usa modal; el usuario cierra el modal o pulsa "Iniciar sesión" y entonces va a `/login`. (Si se prefiere redirect inmediato, debe documentarse y aplicarse en todos los casos.)
3. La función que muestra el modal debe ser única (ej. `window.showSessionExpiredModal`) y llamarse desde el helper de fetch y, si hace falta, desde algún punto común en base_portal para peticiones que no pasen por el helper.
4. Al abrir el modal, si existe `window.uiCloseAllOverlays`, llamarla para cerrar factura rápida, drawers de detalle CFDI, proveedores, etc.

---

## Criterios de aceptación

- [ ] Cualquier 401 en una petición fetch del portal (listados, guardar, sync, bank preview, etc.) muestra el modal de sesión expirada y cierra overlays/drawers abiertos.
- [ ] No hay pantallas donde un 401 deje la UI en estado inconsistente (ej. modal de "Guardando…" abierto sin cerrar).
- [ ] El modal tiene botón o enlace claro a "Iniciar sesión" que lleva a `/login`.
- [ ] La lógica de "mostrar modal en 401" está centralizada (en el helper de fetch y/o una sola función global); no hay código duplicado en cada template que compruebe 401 y haga algo distinto.
- [ ] Probado en al menos: listado clientes (401 al cargar), guardar cliente (401 al guardar), sync SAT (401), bank preview (401 al subir PDF). En todos debe verse el modal y cerrarse overlays si los hay.

---

## Cómo probarlo manualmente

1. **Listado:** Con sesión válida, abrir una lista (ej. clientes). En DevTools, borrar la cookie de sesión o modificar la cookie para que sea inválida. Recargar la lista (o pulsar Reintentar si hay load-error). Debe aparecer el modal "Sesión expirada" y no quedar skeleton ni contenido a medias.
2. **Guardar con sesión expirada:** Abrir formulario de nuevo cliente; esperar o forzar que la cookie expire; pulsar Guardar. Debe mostrarse el modal y cerrarse el modal del formulario si estaba abierto.
3. **Overlays:** Abrir el drawer de detalle CFDI o el modal de factura rápida. Provocar 401 en alguna petición (ej. desde otra pestaña borrar cookie). En la pestaña del portal, disparar una acción que haga fetch (ej. sync). Debe mostrarse el modal de sesión expirada y cerrarse el drawer/modal abierto.
4. **Iniciar sesión:** En el modal, pulsar "Iniciar sesión" y verificar que navega a `/login`.
5. **Formulario full-page:** En el form de factura (`/submit`), si el envío es POST full-page y el servidor devuelve 401, verificar que se redirige a login o se muestra mensaje coherente (según diseño elegido).

---

## Referencias

- AUDIT_README.md — Sección 2.1 (Sesión expirada), Job 5.
- templates/base_portal.html — Modal sesión expirada, uiCloseAllOverlays.
- static/js/ui.js — Manejo de 401 en portalFetchWithTimeout/portalFetchJSON.
