# Notas de desarrollo

## Unificación de error handling en listados (carga vía API)

**Objetivo:** En listados que hacen fetch a la API, mostrar un único mensaje de error (bloque) y no duplicar con toast.

### Reglas aplicadas

- **200 + lista vacía (`[]` o `data.data === []`):** Se muestra el *empty state* (ilustración + texto “Aún no tienes…” / “No hay…”).
- **Respuesta >= 400 (error de red o HTTP):** Se muestra solo el **bloque de error** con mensaje contextual y botón **Reintentar**. No se muestra toast.
- **Toast** se usa solo para **acciones** del usuario: guardar, crear, eliminar, copiar al portapapeles, validaciones de formulario. No para fallos de carga de listas.

### Páginas corregidas / revisadas

| Página | Ruta | Cambio |
|--------|------|--------|
| **Clientes** | `templates/portal_clients.html` | Comentario de convención en `load()`. Error de carga => solo bloque `#custLoadError` con Reintentar. Toast solo en crear/eliminar/copiar. |
| **Productos** | `templates/portal_products.html` | Comentario de convención en `load()`. Error de carga => solo bloque `#prodLoadError`. Toast solo en guardar/copiar. |
| **Cotizaciones** | `templates/portal_quotations.html` | Comentario de convención en `load()`. Error de carga => solo bloque `#quotLoadError`. Toast solo en guardar/copiar/validación. |
| **Proveedores** | `templates/portal_providers.html` | Comentario de convención en `load()`. Error de carga => solo bloque `#provLoadError`. Drawer de facturas del proveedor: error => solo bloque en el panel (sin toast); acepta `data` o `data.data` según respuesta API. |
| **Facturas emitidas** | `templates/portal_issued.html` | Comentario de convención en `loadData()`. Error => solo bloque `#loadErrorState` con Reintentar. 200 + `data.data` vacío => empty state. |
| **Facturas recibidas** | `templates/portal_received.html` | Comentario de convención en `loadData()`. Mismo criterio que emitidas. |

### Otras vistas que cargan listas vía API

- **Portal inicio** (`portal_home.html`): Selectores de cliente/producto para “Generar factura”. En error devuelven `[]` y los dropdowns quedan vacíos; no hay bloque de error ni toast (comportamiento aceptado para este widget).
- **Factura rápida** (`portal_create_quick_choose.html`): Mismo patrón que home; sin toast en error de carga.

### Resumen

En todas las páginas de listado anteriores se cumple:

1. **200 + []** → empty state.
2. **>= 400** → bloque con Reintentar, sin toast.
3. **Toast** solo para acciones (guardar, crear, eliminar, copiar), no para carga de listas.

---

## Continuidad: timeouts + sesión expirada (401) + 5xx sin HTML crudo

**Objetivo:** Evitar pantallas “Cargando…” infinitas y que cualquier expiración de sesión deje la UI en estado consistente.

### Reglas aplicadas

- **Timeout estándar (30s)** en cargas por `fetch`: aborta y el UI muestra un error claro (y, en listados, un bloque con **Reintentar**).
- **401** en cualquier `fetch` que use el helper dispara el modal **“Sesión expirada”** y limpia overlays/drawers (ver `showSessionExpiredModal` en `templates/base_portal.html`).
- **5xx**: el portal **no** debe mostrar HTML con `Exception`/paths. En backend, las rutas del portal ya no retornan `HTMLResponse(..., 400)` con `str(e)`.

### Implementación

- **Helper único**: `window.portalFetchWithTimeout(url, opts, timeoutMs=30000)` en `static/js/ui.js`
  - Usa `AbortController`
  - En `res.status === 401` invoca `window.showSessionExpiredModal()` si existe
- **Listados**: `window.uiFetchJSON` ahora usa el helper, así que los listados quedan cubiertos por timeout/401.
- **Cache de catálogos**: `static/js/catalog-cache.js` usa el helper cuando está disponible, para que los catálogos también tengan timeout/401.
- **Form largo**: `templates/form/_script_form.html` usa `portalFetchWithTimeout` (vía `portalFetch`) en `loadSelect/loadDatalist` y búsqueda ProdServ.
- **Backend**: `routers/portal.py` dejó de responder 400 con HTML crudo en `except Exception`.
