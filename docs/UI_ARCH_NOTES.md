## Notas de arquitectura UI (portal)

### Principios (para evitar regresiones)
- **Modales**: un solo estándar de UI. Preferir `class="modal"` (estilos base en `static/css/portal_shell.css`) y abrir/cerrar con el **modal manager** global.
- **Spacing lateral**: el gap sidebar↔contenido se controla **en un solo lugar** con `--sidebar-gap` (tokens) y el `padding` del contenedor base (shell). No parchar por template.
- **CSS inline**: evitar `<style>` dentro de templates para cosas reutilizables (modales, componentes). Mover a CSS global.

### Modales (source of truth)
- **CSS**: `static/css/portal_shell.css`
  - Define `.modal`, `.modal__backdrop`, `.modal__panel`, scroll/centrado, z-index.
  - Si este CSS no carga globalmente, los “modales” se vuelven `div` normales (típico: “sale abajo y feo”).
- **JS**: `static/js/ui.js`
  - API global:
    - `window.openPortalModal(idOrEl, opts)`
    - `window.closePortalModal(idOrEl)`
  - Features:
    - Cierra con `[data-close]` (backdrop/botón)
    - Cierra con **ESC**
    - **Focus trap** básico
    - Toggle `body.no-scroll`

### Spacing lateral (gap único)
- **Tokens**: `static/css/portal_tokens.css`
  - `--sidebar-content-gap` (valor)
  - `--sidebar-gap` (alias)
- **Aplicación**: `static/css/portal_shell.css`
  - `.portal-container` aplica `padding-left/right: var(--sidebar-gap)`

### Orden de carga recomendado (base)
En `templates/base_portal.html`:
1) `portal_tokens.css` (variables/tokens)
2) `components.css` (componentes base)
3) `portal_components.css` (componentes/utility del portal)
4) `portal_shell.css` (layout shell + modales)
5) `portal_ui_v2.css` (UI moderna)
6) `portal_rail.css` (sidebar/rail)
7) `portal.css` (compat/legacy overrides)
8) `form.css` (formularios)

### Guardrails
- Script dev: `scripts/dev_check_ui.sh`
  - Verifica que `portal_shell.css` esté incluido en `base_portal.html`
  - Reporta uso de `.modal` e inline `<style>` en templates

