# Spec: Paginación y límites en listados

**ID:** `SPEC-08`  
**Origen:** AUDIT_README.md — Performance, Job 7  
**Prioridad:** Media

---

## Objetivo

Evitar respuestas excesivamente grandes en los listados del portal: establecer un límite máximo por petición (ej. 500 ítems) en las APIs de listado y, donde el volumen lo requiera, ofrecer paginación server-side (parámetros limit/offset o page) con controles en la UI (Anterior/Siguiente o "Mostrando X–Y de Z").

---

## Alcance

- Backend: endpoints que devuelven listas (clientes, productos, emitidas, recibidas, cotizaciones, proveedores). Asegurar que acepten `limit` y `offset` (o `page` + `per_page`) y que `limit` tenga un máximo (ej. 500). Si no se envían, usar valores por defecto razonables (ej. limit=100, offset=0).
- APIs afectadas (en `routers/api.py` y/o `routers/portal.py`): las que sirven datos para los listados del portal (GET de clientes, productos, y las rutas que devuelven emitidas/recibidas por mes, cotizaciones, proveedores). Revisar cada una y aplicar límite máximo y paginación.
- Frontend: en las pantallas de listado que hoy cargan "todo" en una sola petición, si se introduce paginación server-side, añadir controles (Anterior / Siguiente, o "Mostrando 1–100 de 350") y llamar a la API con offset/page al cambiar de página. Si se decide mantener una sola carga pero con límite máximo (ej. 200), mostrar mensaje "Mostrando los primeros 200" cuando haya más registros y opcionalmente un enlace o botón "Cargar más" o "Ver todos" (según diseño).
- Documentar en la API o en documentación interna el límite máximo y los parámetros de paginación.

---

## Fuera de alcance

- Cambiar la estructura de datos de la API (solo añadir parámetros y validación).
- Paginación en listados de admin (puede quedar para otra spec).
- Optimización de queries (índices, N+1) más allá de limit/offset.
- Cambiar el formato de respuesta (ej. envolver en `{ "items": [], "total": N }`) si la API actual no lo hace; se puede mantener compatibilidad con array directo y añadir headers o metadata para total si hace falta.

---

## Archivos a tocar

| Archivo / directorio | Cambio previsto |
|----------------------|-----------------|
| `routers/api.py` | Endpoints de customers, products y otros listados: leer query params `limit`, `offset` (o `page`); validar `limit` <= 500 (o valor acordado); aplicar LIMIT/OFFSET en la query SQL; devolver total si es necesario para la UI (en body o header). |
| `routers/portal.py` | Rutas que devuelven listas para emitidas, recibidas, cotizaciones (por mes o global): aceptar limit/offset; aplicar límite máximo; modificar la query para paginación. |
| `templates/portal_clients.html` | Si la API pasa a paginación: añadir controles Anterior/Siguiente y llamar a la API con offset; mostrar "Mostrando X–Y de Z". |
| `templates/portal_products.html` | Igual si aplica. |
| `templates/portal_issued.html` | Igual; hoy puede cargar LIMIT 300; pasar a limit/offset y controles de página. |
| `templates/portal_received.html` | Igual. |
| `templates/portal_quotations.html` | Igual. |
| `templates/portal_providers.html` | Igual si la lista de proveedores es paginada. |
| Documentación (README, API_NOTES o similar) | Documentar límite máximo (500) y parámetros `limit`, `offset` (o `page`, `per_page`) para cada endpoint de listado. |

---

## Reglas

1. Ningún endpoint de listado debe devolver más de 500 ítems en una sola respuesta (o el máximo acordado). Si el cliente pide limit=10000, capar a 500.
2. Los parámetros de paginación deben ser consistentes: o bien `limit` + `offset`, o bien `page` + `per_page`. Documentar cuál se usa.
3. La respuesta debe permitir a la UI saber si hay más páginas: ya sea devolviendo `total` (total de registros) o `has_more`, o la UI puede inferir si recibió menos ítems que el limit.
4. Por defecto, si no se envían parámetros, usar limit=100 (o 50) y offset=0 para no romper clientes que no paginan; o mantener el comportamiento actual y solo capar el máximo.
5. En el front, si se usa paginación server-side, no cargar todas las páginas en memoria; solo la página actual.

---

## Criterios de aceptación

- [ ] Todas las APIs de listado del portal tienen un límite máximo (ej. 500) y aceptan parámetros de paginación (limit, offset o page, per_page).
- [ ] Si el cliente pide limit mayor al máximo, la API devuelve como máximo el máximo y no error (o devuelve 400 con mensaje; decidir y documentar).
- [ ] Las pantallas de listado del portal (al menos emitidas, recibidas; y las demás según alcance) usan paginación: muestran controles y piden solo la página actual.
- [ ] Se documenta el límite máximo y los parámetros de paginación para los endpoints afectados.
- [ ] Con muchos registros (ej. 400 emitidas), la primera carga no devuelve las 400 en una sola petición; devuelve la primera página (ej. 100) y la UI permite pasar a la siguiente.

---

## Cómo probarlo manualmente

1. **Límite máximo:** Llamar a `/api/customers?limit=2000` (o el endpoint que sea). Debe devolver como máximo 500 (o el máximo definido) y no fallar.
2. **Paginación:** Llamar con `limit=10&offset=0` y luego `limit=10&offset=10`. Debe devolver conjuntos distintos de ítems.
3. **UI:** En emitidas o recibidas con muchos registros, verificar que aparezcan controles Anterior/Siguiente (o "Mostrando 1–100 de 350") y que al cambiar de página se carguen los datos de esa página.
4. **Total:** Si la UI muestra "Mostrando X–Y de Z", verificar que Z coincida con el total real (la API debe devolver el total o la UI calcularlo si aplica).
5. **Compatibilidad:** Si hay clientes o pantallas que no envían limit/offset, verificar que sigan funcionando con valores por defecto.

---

## Referencias

- AUDIT_README.md — Sección 7 (Performance), Job 7.
- routers/api.py — Endpoints de customers, products.
- routers/portal.py — Rutas que devuelven listas (emitidas, recibidas, etc.).
