# Spec: Empty states / errores / éxito consistentes

**ID:** `SPEC-04`  
**Origen:** AUDIT_README.md — UX, Job 6  
**Prioridad:** Media

---

## Objetivo

Unificar la convención en todas las listas del portal: (1) lista vacía = empty state con icono, título, descripción y CTA si aplica; (2) error de carga / timeout = load-error con mensaje y botón "Reintentar"; (3) éxito tras guardar/enviar = mismo criterio (toast o toast + cierre de modal) en todos los formularios. No confundir "lista vacía" (200 + `[]`) con "error de carga" (timeout/red/5xx).

---

## Alcance

- Todas las pantallas de listado que cargan datos por fetch: clientes, productos, emitidas, recibidas, cotizaciones, proveedores. Cada una debe tener:
  - Skeleton inicial mientras carga.
  - Bloque `portal_load_error` (id consistente, ej. `loadErrorState`) visible solo cuando la petición falla (timeout, red, 4xx/5xx), con mensaje y "Reintentar".
  - Bloque `portal_empty_state` visible solo cuando la petición devuelve 200 y la lista está vacía.
- Pantallas que hoy solo tienen empty (portal_clients, portal_products): añadir `portal_load_error` y mostrarlo cuando falle la carga.
- Mensajes de éxito al guardar (cliente, producto, cotización): unificar criterio (toast con título "Guardado" y mensaje breve; cerrar modal si aplica).
- Documentar la convención en `docs/UI_PATTERNS.md` si no está ya.

---

## Fuera de alcance

- Cambiar el diseño visual de los bloques (solo asegurar que existan y se muestren en el caso correcto).
- Paginación (spec 08).
- Timeouts en fetch (spec 02; esta spec asume que ya se usa el helper y que en error se muestra load-error).
- Sanitización de mensajes en load-error (se puede hacer en esta spec o en una aparte; si se incluye, escapar siempre el texto en `loadErrorStateMsg` para evitar XSS).

---

## Archivos a tocar

| Archivo / directorio | Cambio previsto |
|----------------------|-----------------|
| `templates/portal_clients.html` | Incluir `portal_load_error` (desde _ui_components.html); en el script, al fallar la carga mostrar load-error y ocultar empty; al tener 200 y lista vacía mostrar empty y ocultar load-error. |
| `templates/portal_products.html` | Igual. |
| `templates/portal_issued.html` | Verificar que load-error y empty no se muestren a la vez; lógica clara: error → load-error, 200 y vacío → empty, 200 y datos → tabla. |
| `templates/portal_received.html` | Igual. |
| `templates/portal_quotations.html` | Igual. |
| `templates/portal_providers.html` | Igual. |
| `templates/portal/_ui_components.html` | Verificar que `portal_empty_state` y `portal_load_error` tengan ids/documentación para uso consistente. |
| `docs/UI_PATTERNS.md` | Reglas claras: 200 + [] → empty; timeout/red/4xx/5xx → load-error; éxito guardar → toast (y cerrar modal). No usar load-error para "no hay resultados". |
| Opcional: templates que muestren éxito al guardar | Revisar que usen toast de forma consistente (ej. `window.uiToast({ type: 'success', title: 'Guardado', message: '...' })`) y cierren el modal de edición si aplica. |

---

## Reglas

1. **Empty state:** Solo cuando la API devuelve 200 y el cuerpo es una lista vacía (o 0 ítems). No mostrar empty cuando hubo error de red o timeout.
2. **Load-error:** Solo cuando la petición falla (timeout, red, 4xx, 5xx). Incluir mensaje genérico ("No pudimos cargar esto ahora") y botón "Reintentar" que vuelva a ejecutar la carga. No usar load-error para "no hay resultados".
3. **Skeleton:** Mostrar al iniciar la carga; ocultar cuando llegue la respuesta (éxito, vacío o error). No dejar skeleton visible junto con load-error o empty de forma indefinida.
4. **Éxito:** Tras guardar (cliente, producto, cotización), mostrar toast de éxito y cerrar el modal de edición/creación. Mismo patrón en todas las pantallas.
5. **Mensajes en load-error:** Si se muestra un mensaje dinámico (ej. "La solicitud tardó demasiado"), asegurar que el texto esté escapado (no inyectar HTML del servidor sin escapar) para evitar XSS.

---

## Criterios de aceptación

- [ ] Todas las listas (clientes, productos, emitidas, recibidas, cotizaciones, proveedores) tienen ambos bloques: empty state y load-error, y la lógica los muestra según el caso (error → load-error, 200 vacío → empty, 200 con datos → contenido).
- [ ] En ninguna lista se muestra empty state cuando la petición falló por timeout o error de red; en ese caso solo se muestra load-error con Reintentar.
- [ ] Al guardar cliente/producto/cotización, se muestra toast de éxito y se cierra el modal de forma consistente.
- [ ] docs/UI_PATTERNS.md describe la convención: cuándo empty, cuándo load-error, cuándo éxito (toast + cierre modal).
- [ ] Los mensajes mostrados en load-error no incluyen HTML sin escapar (si se usa innerHTML o textContent con variable, la variable debe estar escapada).

---

## Cómo probarlo manualmente

1. **Lista vacía:** Con datos vacíos (o API que devuelva []), cargar clientes, productos, etc. Debe verse empty state, no load-error.
2. **Error de carga:** Cortar red o detener servidor y cargar una lista. Debe verse load-error con "Reintentar". No debe verse empty state.
3. **Reintentar:** Con load-error visible, pulsar Reintentar con red restaurada; debe cargar la lista o el empty state según corresponda.
4. **Guardar:** Crear/editar cliente, producto, cotización; guardar. Debe aparecer toast "Guardado" y cerrarse el modal.
5. **Revisar cada lista:** Clientess, Productos, Emitidas, Recibidas, Cotizaciones, Proveedores — verificar en cada una los tres estados (cargando → contenido, cargando → empty, cargando → load-error).

---

## Referencias

- AUDIT_README.md — Sección 4 (UX/UI), Job 6.
- docs/UI_PATTERNS.md — Empty state vs load-error.
- templates/portal/_ui_components.html — portal_empty_state, portal_load_error.
