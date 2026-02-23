## PortalFetch (helper unificado)

Este documento define el helper único para `fetch` en el portal: **timeout + 401 + retry**.

### API

El helper vive en `static/js/ui.js`:

- `window.portalFetchJSON(url, opts = {}, { timeoutMs = 30000, retry = 1 } = {})`
  - `credentials: 'same-origin'` por default
  - header `Accept: 'application/json'` por default
  - `AbortController` con timeout
  - **401**: ejecuta `uiCloseAllOverlays()` + `showSessionExpiredModal()` y retorna `{ ok:false, status:401, error:'unauthorized' }`
  - **retry**: 1 reintento solo para **timeout/network** y solo en **GET/HEAD**

Retorno:

- OK:
  - `{ ok:true, status, data }`
- Error:
  - `{ ok:false, status, error:'timeout'|'network'|'unauthorized'|'http'|'parse', detail }`

### UI cleanup (401)

- `window.uiCloseAllOverlays()` cierra overlays/drawers/modales abiertos y limpia botones en loading.
- `window.showSessionExpiredModal()` (en `templates/base_portal.html`) muestra el modal global “Sesión expirada”.

### Regla UX (listas vs acciones)

- **Listas**:
  - `200 + []` → empty state con CTA
  - error → **bloque único** con “Reintentar” (sin toast)
- **Acciones** (create/update/delete):
  - success → overlay (mutación importante) o toast (acción pequeña)
  - error → toast error con mensaje accionable

### Compatibilidad

- `window.uiFetchJSON()` ahora es un wrapper que usa `portalFetchJSON` y mantiene el contrato `{ ok, status, data, error }` para templates existentes.

