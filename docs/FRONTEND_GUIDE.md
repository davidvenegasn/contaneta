# Guía de frontend — ContaNeta

Convenciones Jinja, CSS, JS y cómo editar templates y estilos sin romper consistencia ni accesibilidad.

---

## 1. Stack

- **Templates:** Jinja2 (FastAPI Jinja2Templates). Sin React ni otro framework.
- **CSS:** Archivos estáticos en `static/css/`. Sin Tailwind ni build step.
- **JS:** Vanilla en `static/js/`. Sin bundler.

---

## 2. Estructura de templates

### 2.1 Bases

| Template | Uso |
|----------|-----|
| `base_portal.html` | Shell del portal: meta, CSRF, estilos, fuentes, sidebar, topbar, breadcrumbs, menú usuario, `{% block content %}`, toasts y scripts. |
| `base_admin.html` | Layout del área admin. |
| `base_portal_v2.html` | Variante shell (rail + drawer) si se usa PORTAL_SHELL_V2. |

### 2.2 Herencia

Las páginas del portal extienden `base_portal.html`:

```jinja2
{% extends "base_portal.html" %}
{% block title %}Título de la página{% endblock %}
{% block content %}
  ...
{% endblock %}
```

Variables que suele inyectar el backend en `_render_portal`:

- `request`, `issuer`, `title`, `active_page`, `csrf_token`
- `error`, `has_nomina`, `show_welcome_popup`, `is_demo_view`, `is_impersonating`
- `menu_sat_configured`, `menu_catalog_ok`, `dev_debug_panel`, `portal_shell_v2`
- Cualquier `extra` o `template_vars` por ruta

### 2.3 Bloques disponibles en base_portal.html

- `title` — Título de la página (y `<title>`).
- `content` — Cuerpo principal.
- Opcionales según página: bloques para acciones de topbar, etc. (revisar base para nombres exactos).

### 2.4 Includes y parciales

- `form/_section_*.html` — Secciones del formulario de factura (comprobante, receptor, conceptos, IVA, retenciones, extras, resumen).
- `portal/_ui_components.html` — Componentes reutilizables del portal.
- `partials/` — Listas (issued_list, received_list, clients_list, providers_list, bank_upload, etc.).
- `components/portal_drawer.html`, `components/portal_rail.html` — Drawer y rail.
- `components/breadcrumbs.html` — Breadcrumb del topbar (requiere `active_page` del contexto).

**Regla:** No usar nombres de template dinámicos desde variables de usuario. Siempre literales (evita TemplateNotFound y riesgos de path traversal).

### 2.5 Navegación activa

- `active_page` se pasa desde el router (ej. `"issued"`, `"clients"`, `"create"`).
- En base_portal, el sidebar/topbar usan `active_page` para marcar el ítem activo (clase o `aria-current` según implementación).

### 2.6 Uso de request en templates

- `request.path` para comparar rutas o mostrar en breadcrumbs (Inicio › Página actual).
- No exponer en template datos sensibles de `request.state` salvo los que el backend inyecta explícitamente (issuer, user_id, etc.).

---

## 3. CSS

### 3.1 Orden de carga (base_portal.html)

1. `form.css`
2. `portal_tokens.css` — **Tokens (fuente de verdad): tipografía, colores, spacing, radius, sombras.**
3. `components.css` — Componentes UI (.ui-input, .ui-btn, .ui-card, .ui-table, etc.).
4. `portal.css` — Entrada principal: importa internamente `portal_shell.css`, `portal_components.css`, `portal_pages.css` y contiene el resto de reglas (topbar, páginas, responsive). Ver `docs/CSS_ARCHITECTURE.md`.
5. `portal_ui_v2.css`, `portal_rail.css`
6. `portal_shell_v2.css` — Solo si `portal_shell_v2` es true.

### 3.2 Tokens (portal_tokens.css)

Usar variables en lugar de valores fijos:

- **Tipografía:** `--font-family`, `--text-xs` … `--text-3xl`, `--fw-normal` … `--fw-bold`, `--leading-*`.
- **Colores:** `--text`, `--text-muted`, `--bg`, `--surface`, `--border`, `--primary`, `--accent`, `--focus-ring`, etc.
- **Espaciado:** `--space-1` … `--space-*`.
- **Radius/sombras:** `--radius`, `--shadow-*`.

Evitar añadir `!important`; si hace falta, revisar especificidad o orden de reglas.

### 3.3 Capas recomendadas

- **Tokens:** solo variables en `portal_tokens.css`.
- **Componentes:** clases reutilizables en `components.css`.
- **Páginas/layout:** en `portal.css` o en hojas por sección si se añaden más adelante.

No duplicar reglas idénticas en varios archivos; referenciar una sola definición o extender con clases compuestas.

### 3.4 Modo noche

- Clase `nightmode` en `<html>` (controlada por JS desde `localStorage.portal_nightmode`).
- Variables en `portal_tokens.css` (o en bloque `html.nightmode`) para colores en modo noche.
- Respetar `prefers-reduced-motion` (ver sección Accesibilidad).

### 3.5 Responsive

- Breakpoints y tablas con scroll horizontal (`.table-wrap`) en `portal.css`.
- Drawer para sidebar en móvil; touch targets ~44px donde sea posible (ver MOBILE_CHECKLIST.md).

---

## 4. JavaScript

### 4.1 Archivos globales del portal

- **catalog-cache.js** — Cache GET de catálogos (clientes/productos) con TTL; se carga en `<head>` para prefetch en Home.
- **ui.js** — Toasts (`window.uiToast`, `portalToast`), loading en botones (`uiSetButtonLoading`, `uiSetButtonSuccess`), skeleton para tablas, success overlay.
- **portal_drawer.js**, **portal_resumen_collapse.js**, **portal_shell_v2.js** — Comportamiento drawer, collapse, shell v2.

Cargar con `defer` cuando sea posible y solo en páginas que usen el script (base_portal incluye los que aplican a todo el portal).

### 4.2 Fetch y errores

- Evitar que un error de `fetch` (4xx/5xx) rompa la UI: mostrar bloque “No se pudo cargar” con botón “Reintentar” y no duplicar mensaje en toast.
- En docs y scripts de auditoría se recomienda usar un helper con timeout y manejo 401 unificado (p. ej. `portalFetchWithTimeout` o similar) para no repetir lógica.

### 4.3 Event listeners

- No duplicar listeners en el mismo elemento (evitar múltiples bind al mismo botón sin off).
- En SPA-like (listas que se recargan por fetch), considerar delegación o limpieza al desmontar.

### 4.4 Compatibilidad móvil

- Touch: no depender solo de hover; usar eventos táctiles o CSS que funcione con touch.
- Teclado: no ocultar botones críticos detrás del teclado virtual (viewport, scroll).

---

## 5. Accesibilidad

### 5.1 ARIA y roles

- Botones solo con icono: `aria-label` descriptivo (ej. “Abrir menú”, “Cerrar menú”).
- Menú usuario: `aria-haspopup="menu"`, `aria-expanded`, `role="menu"` y `role="menuitem"`.
- Sidebar/drawer: `aria-label`, `aria-controls`, `aria-expanded`, `aria-hidden` según estado.
- Modales/drawers: `aria-modal`, focus trap y cierre con ESC (documentado en ACCESSIBILITY.md y BACKLOG).

### 5.2 Focus

- Usar `:focus-visible` para anillo de foco (no solo `:focus`), así no aparece en clic con ratón.
- No usar `outline: none` sin reemplazo; en portal_tokens está `--focus-ring` y `--focus-ring-offset`.

### 5.3 Contraste

- Texto y fondos deben cumplir contraste mínimo razonable (WCAG AA recomendado para texto normal).
- Colores de texto y bordes usar variables (--text, --text-muted, --border) para mantener coherencia.

### 5.4 Movimiento

- Respetar `prefers-reduced-motion: reduce`: en `portal.css` y `form.css` hay bloques que reducen duraciones a 0.01ms o desactivan animaciones.
- No añadir animaciones nuevas sin considerar `prefers-reduced-motion` (ver docs/MOTION.md).

---

## 6. Formularios y CSRF

- Todo formulario que modifique estado (login, signup, forgot, reset, onboarding, FIEL, submit factura, admin) debe:
  - Incluir `<input type="hidden" name="csrf_token" value="{{ csrf_token }}">` o enviar `X-CSRF-Token` en peticiones fetch.
  - El backend debe verificar con `csrf_service.verify_csrf_token()`.
- El meta `csrf-token` en base_portal permite que el JS lea el token para enviarlo en headers.

---

## 7. Cómo editar sin romper

1. **Nueva página portal:** Extender `base_portal.html`, rellenar `title` y `content`; en el router usar `_render_portal(..., template_name="portal_xxx.html", active_page="xxx", ...)`.
2. **Nuevo estilo:** Preferir clases en `components.css` o `portal.css` usando variables de `portal_tokens.css`. Evitar estilos inline salvo casos puntuales (p. ej. dinámicos desde backend).
3. **Nuevo JS:** Añadir script con `defer` en el bloque correspondiente de base o en la página que lo use; asegurar que no genere errores si el DOM no tiene el elemento.
4. **Empty states:** En listas que cargan por API, definir bloque “sin datos” y “error de carga” con mensaje único y “Reintentar” (evitar doble mensaje toast + bloque).
5. **Nuevo formulario POST:** Añadir csrf_token y verificación en el endpoint.

---

## 8. Referencias

- `templates/base_portal.html` — Estructura y bloques.
- `static/css/portal_tokens.css` — Tokens.
- `static/css/components.css` — Componentes UI.
- `docs/ACCESSIBILITY.md` — Focus, ARIA, contraste.
- `docs/MOTION.md` — Animaciones y prefers-reduced-motion.
- `docs/DESIGN_SYSTEM_V1.md` — Sistema de diseño si existe.
- `MOBILE_CHECKLIST.md` — Pruebas móvil.
