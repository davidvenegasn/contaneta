# UX Audit Report — Portal (Full UX Polish)

**Branch:** `agent/full-ux-polish`  
**Alcance:** templates/, static/css/, static/js/ + pequeños ajustes API (vacío ≠ error).  
**Objetivo:** Interacción premium, consistencia visual, mobile first, confianza (mensajes claros, sin errores feos en vacío).

---

## Páginas revisadas

| Página | Ruta / Template | Estado |
|--------|-----------------|--------|
| Base (layout) | base_portal.html | ✅ Revisado |
| Inicio | portal_home.html | ✅ Revisado |
| Facturas emitidas | portal_issued.html | ✅ Revisado |
| Facturas recibidas | portal_received.html | ✅ Revisado |
| Generar factura | form.html + form/_section_*.html | ✅ Revisado |
| Clientes | portal_clients.html | ✅ Revisado |
| Productos | portal_products.html | ✅ Revisado |
| Proveedores | portal_providers.html | ✅ Revisado |
| Cotizaciones | portal_quotations.html | ✅ Revisado |
| Detalle CFDI | portal_cfdi_detail.html | ✅ Revisado |
| Resumen | portal_summary.html | ✅ Revisado |
| Config SAT | portal_config_sat.html | ✅ Revisado |
| Nómina | portal_nomina.html | ✅ Revisado |
| Success (post-factura) | success.html | ✅ Revisado |

---

## A) Global (base_portal)

| Check | Problema | Solución |
|-------|----------|----------|
| Topbar y sidebar consistentes | — | Topbar fija con título e icono por página; sidebar con nav-item y clase `.active` según `active_page`. |
| Activo marcado | — | `.nav-item.active` con fondo `--accent-soft`, borde y barra lateral `--accent` (portal.css). |
| Tipografía base 16px | — | `portal_tokens.css`: `--text-base: 1rem`; body en portal.css con `font-size: 16px` y `var(--text-base)`. |
| Headings más grandes | — | `.portal h2` con `--text-2xl`, `.portal h3` con `--text-xl`; `.section-title` con `--text-lg`. |
| Spacing correcto | — | `--card-padding: 22px`, `--section-gap: 22px`; `.main-inner`, cards y secciones usan variables. |
| Focus states accesibles | — | `components.css` y `portal.css`: `:focus-visible` con outline/box-shadow; inputs con `0 0 0 3px var(--accent-soft)`. |
| Targets táctiles 44px | — | En `@media (max-width: 768px)` botones, `.filters-toggle`, `.portal-topbar__action`, `.nav-item` con min-height 44px. |
| No scroll lateral global | — | `body`, `.main`, `.portal-shell` con `overflow-x: hidden`; contenido en `.main-inner` con `min-width: 0`. |

**Cómo probar:** Navegar por todas las secciones del menú; comprobar que la opción activa se resalta; redimensionar a 390px y comprobar que no aparece scroll horizontal; tabular y comprobar focus visible en botones e inputs.

---

## B) Sistema de feedback

| Check | Problema | Solución |
|-------|----------|----------|
| Toasts globales | — | `#toastStack` en base_portal; `window.portalToast({ type, title, message, ttl })`; success/error/info. |
| Skeleton loaders listas | — | Emitidas/recibidas: skeleton en tabla y en lista móvil (invoiceListMobile); clientes/productos/proveedores/cotizaciones: skeleton en tbody inicial. `ui.js`: `uiSkeletonTableRows(cols, rows)`. |
| Empty states (no alerts) | — | Todas las listas: bloque `.empty-state` con título “Aún no hay…”, descripción y CTA (Crear cliente, Sync SAT, etc.). Sin toasts ni alertas cuando la API devuelve 200 + []. |
| Error solo si HTTP ≥ 400 | — | Bloque “No se pudo cargar” con Reintentar solo cuando `!res.ok` o `catch`; vacío (0 filas) muestra empty state amigable. |

**Cómo probar:** Dejar listas vacías (clientes, productos, etc.) y comprobar que se ve el empty state y no un mensaje de error. Simular fallo (ej. sin red) y comprobar que aparece “No se pudo cargar” + Reintentar sin toast duplicado.

---

## C) Flujos críticos

### C1) Home / Factura rápida

| Check | Estado |
|-------|--------|
| Si falta cliente/producto: CTAs claras | ✅ Selects con hint “Aún no tienes…”; botones “+ Añadir cliente” / “+ Añadir producto”. |
| Al guardar cliente/producto: toast + select actualizado | ✅ Llamada a API create; toast success; recarga de opciones en select y valor seleccionado. |

### C2) Generar factura

| Check | Estado |
|-------|--------|
| Conceptos sin encimes, responsive | ✅ form.css: item-row-top y concept-card en 1–2 columnas en móvil; concept-card__row1/row2 apilados. |
| IVA/retenciones compactos | ✅ Secciones con labels y campos alineados; form.css con breakpoints 520/768/1024. |
| Success al generar: overlay con acciones | ✅ success.html con overlay; acciones descargar/copiar/enlace según contexto. |

### C3) Emitidas / Recibidas

| Check | Estado |
|-------|--------|
| Toolbar limpia, filtros claros | ✅ Filtros en panel colapsable; botón “Filtros” con badge de cantidad activa. |
| SAT Sync sutil en lista (no topbar) | ✅ Sync solo en topbar para home/nómina; en emitidas/recibidas: barra sutil en header de card (Último sync + botón “Sync SAT” ghost). |
| Estado “último sync” + “En proceso” | ✅ Texto “Último sync: fecha”; badge “En proceso…” con spinner cuando status running; poll actualiza estado. |
| Acciones en móvil | ✅ A ≤640px lista en cards (invoice-card-mobile) con botones Detalle, XML, PDF en fila inferior. |

### C4) Proveedores

| Check | Estado |
|-------|--------|
| Drawer “Ver facturas” profesional | ✅ ui-overlay + ui-drawer; scroll interno en panel; backdrop; cierre con ESC y botón; enlace “Ver todas en Facturas recibidas”. |

### C5) Cotizaciones

| Check | Estado |
|-------|--------|
| Modal crear: layout pro, footer sticky | ✅ quot-modal__foot con position sticky en móvil; botones full-width y min-height 48px; tabla de conceptos en cards en 640px. |

---

## D) Micro-interacciones

| Check | Estado |
|-------|--------|
| Transiciones 120–180ms | ✅ Botones, cards, tablas con transition 140–180ms en portal.css y components.css. |
| Hover/press | ✅ .btn :hover y :active con sombra/transform; respetando prefers-reduced-motion (transform none en reduce). |
| Slide del drawer | ✅ Sidebar con transform y transition; backdrop con opacity. |
| prefers-reduced-motion | ✅ Bloque global reduce con animation-duration 0.01ms; fade-in y page-loading-bar desactivados en reduce. |

---

## Resumen de problemas encontrados y soluciones

1. **Errores feos con listas vacías**  
   **Solución:** Empty states en todas las listas; bloque “No se pudo cargar” + Reintentar solo para fallos reales; sin toast cuando solo hay 0 filas (cambios en portal_clients, portal_products, portal_providers, portal_quotations, portal_issued, portal_received).

2. **SAT Sync muy prominente en topbar**  
   **Solución:** Sync en topbar solo en home y nómina; en emitidas/recibidas reubicado a barra sutil en la card de lista (portal_list_sync_bar.html, base_portal, portal_issued, portal_received).

3. **Móvil: tabla ancha y acciones apretadas**  
   **Solución:** A ≤640px lista en cards (invoice-card-mobile) con acciones en fila; padding 12/16px; touch targets 44px (portal.css + templates emitidas/recibidas).

4. **Consistencia tipografía y spacing**  
   **Solución:** portal_tokens.css con escala tipográfica y variables; portal.css con body 16px, headings y cards con --card-padding y --section-gap.

5. **Focus y accesibilidad**  
   **Solución:** focus-visible con anillo en botones e inputs (components.css); sin outline en :focus:not(:focus-visible).

---

## Cómo probar (resumen)

- **Global:** Cambiar de sección y comprobar activo en sidebar; probar con teclado (Tab, Enter); 390px sin scroll horizontal.
- **Feedback:** Listas vacías → empty state; fallo de red → “No se pudo cargar” + Reintentar; acciones que guardan → toast.
- **Emitidas/Recibidas:** Sync en barra de la lista; en móvil ver cards y botones Detalle/XML/PDF.
- **Proveedores:** “Ver facturas” abre drawer; scroll interno; ESC cierra.
- **Cotizaciones:** Modal nueva cotización con footer fijo en móvil y botones grandes.

Screenshots no incluidos; descripción por módulo arriba.
