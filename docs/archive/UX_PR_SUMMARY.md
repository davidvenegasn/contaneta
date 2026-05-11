# Before/After por módulo — Full UX Polish

Resumen para la descripción del PR en `agent/full-ux-polish`.  
Alcance: templates/, static/css/, static/js/ + pequeños ajustes API (vacío ≠ error).

---

## Global (base_portal, layout)

| Antes | Después |
|-------|--------|
| Sidebar/topbar sin estado activo claro | Ítem activo con `.active`: fondo suave, barra lateral y borde; topbar con título e icono por página. |
| Tipografía y spacing inconsistentes | Base 16px, headings escalados (--text-2xl, --text-xl), --card-padding y --section-gap unificados. |
| Focus poco visible | :focus-visible con outline/box-shadow en botones e inputs (accent-soft). |
| Scroll horizontal en móvil | body, .main, .portal-shell con overflow-x: hidden; .main-inner con min-width: 0. |
| Targets táctiles pequeños en móvil | En @media 768px: botones, .filters-toggle, .nav-item con min-height 44px. |

---

## Sistema de feedback (todo el portal)

| Antes | Después |
|-------|--------|
| Sin toasts unificados | #toastStack + portalToast({ type, title, message }); success/error/info. |
| Listas vacías o en carga sin feedback | Skeleton loaders en emitidas/recibidas, clientes, productos, proveedores, cotizaciones; empty states con título, descripción y CTA (no alertas). |
| Vacío tratado como error | API 200 + [] muestra empty state; bloque "No se pudo cargar" + Reintentar solo cuando HTTP ≥ 400 o catch. |
| Toasts duplicados en error de carga | Un solo mensaje: o toast o bloque "No se pudo cargar", no ambos. |

---

## Home / Factura rápida

| Antes | Después |
|-------|--------|
| Selects vacíos sin guía | Hint "Aún no tienes clientes/productos" y CTAs "+ Añadir cliente", "+ Añadir producto". |
| Tras guardar cliente/producto | Toast success + select actualizado con el nuevo ítem. |

---

## Generar factura (form)

| Antes | Después |
|-------|--------|
| Conceptos que se encimaban en móvil | item-row-top y concept-card en 1 columna en móvil; concept-card__row1/row2 apilados; breakpoints 520/768/1024. |
| IVA/retenciones desalineados | Secciones compactas con labels y campos alineados. |
| Post-generación | success.html con overlay y acciones descargar/copiar/enlace. |

---

## Emitidas / Recibidas

| Antes | Después |
|-------|--------|
| Sync SAT en topbar | Sync solo en barra de la lista (portal_list_sync_bar); "Último sync: …" o "Aún no se ha sincronizado"; en móvil botón solo icono. |
| Tabla ancha en móvil | En 640px lista en cards (invoice-list-mobile); cada factura = card con fecha, nombre, concepto, total, estatus y acciones (Detalle, XML, PDF) con targets táctiles. |
| Toolbar y filtros | Toolbar limpia; filtros en panel colapsable; sin scroll horizontal. |

---

## Proveedores

| Antes | Después |
|-------|--------|
| "Ver facturas" sin drawer definido | Drawer con scroll interno, overlay, cierre con X o ESC; focus trap y layout estable. |

---

## Cotizaciones

| Antes | Después |
|-------|--------|
| Modal crear cotización poco usable en móvil | Modal con footer sticky; tabla/conceptos responsive; botones Cancelar, Guardar borrador, Enviar grandes y accesibles. |

---

## Micro-interacciones

| Antes | Después |
|-------|--------|
| Transiciones bruscas | Transiciones 120–180ms en hover/press y slide del drawer. |
| Sin respeto a preferencias de movimiento | prefers-reduced-motion: reduce aplicado donde corresponde. |

---

## Documentación añadida

- **UX_AUDIT_REPORT.md**: páginas revisadas, checklist A–D, problemas + soluciones, cómo probar.
- **QA_STEPS.md**: sección "Pruebas UX (15 min)" con U1–U15 (empty states, Sync, 390px, drawer, modal, Reintentar, ítem activo, concepto, toast, focus).
- **MOBILE_CHECKLIST.md**: validación 390px y 768px (sin scroll lateral, listas en cards, targets 44px, drawer/modal, breakpoints usados).

---

**Cómo probar:** Seguir QA_STEPS.md sección "Pruebas UX (15 min)" y MOBILE_CHECKLIST.md en 390px y 768px.
