# Mobile Checklist — 390px / 768px (demo móvil)

Validación de que el portal es usable y demostrable en móvil **390px** sin scroll lateral ni elementos encimados.

**Cómo probar:** DevTools → Toggle device toolbar (Ctrl+Shift+M / Cmd+Shift+M); elegir **390×844** (iPhone 14) o 768×1024 (iPad); recargar y recorrer cada sección.

---

## 390px (móvil estrecho — pase final demo)

| # | Página / Área | Check | Estado |
|---|----------------|-------|--------|
| 1 | **Global** | **Cero scroll horizontal** en body en ninguna vista | html/body overflow-x: clip; .portal-shell, .main, .main-inner overflow-x: hidden |
| 2 | Global | Padding lateral 12–16px (no contenido pegado al borde) | .main, .main-inner en @media 480px / 390px |
| 3 | Global | Topbar con título e icono legibles; menú usuario accesible | .portal-topbar__text con max-width; .topbar-user táctil |
| 4 | Global | Sidebar drawer: abre con hamburguesa; cierra con X o backdrop; transición suave | .sidebar, .sidebar-backdrop |
| 5 | Global | Botones y enlaces con min-height/área **≥44px** | .btn, .nav-item, .filters-toggle; @media 390px refuerza 44px |
| 6 | Home | Cards de métricas y bloques apilados en 1 columna | .dashboard-metrics 1fr; .dashboard-half-row 1fr |
| 7 | Home | Factura rápida: selects y botón "Generar factura" full-width si aplica | .quick-invoice-actions .btn width 100% |
| 8 | Home | Empty states y CTAs (onboarding) con targets táctiles | .onboarding-checklist__item a con min-height 44px |
| 9 | **Emitidas / Recibidas** | **Resumen (mes + métricas) no deslizable**; facturas en **cards** con **scroll interno** en el card | .ym-card flex-shrink: 0; .card--invoice-list .card__body overflow-y: auto; .invoice-list-mobile visible |
| 10 | Emitidas / Recibidas | Acciones por factura: Detalle, XML, PDF en fila inferior; botones **44px** | .invoice-card-mobile__actions .btn min-height 44px |
| 11 | Emitidas / Recibidas | Barra Sync: "Último sync" en una línea; botón Sync solo icono | .list-sync-bar__btn-label display none; .list-sync-bar__meta max-width 140px |
| 12 | Emitidas / Recibidas | Filtros: panel colapsable; inputs y selects usables | .filters-panel; inputs con altura 46px |
| 13 | Clientes / Productos / Proveedores | Tabla con scroll horizontal **solo dentro** de .table-wrap (no en body) | .table-wrap overflow-x: auto; body sin scroll horizontal |
| 14 | Clientes / Productos / Proveedores | Empty state y bloque "No se pudo cargar" legibles; botón Reintentar táctil | .empty-state, .btn min-height 44px |
| 15 | **Proveedores** | **Drawer "Ver facturas" perfecto en móvil**: full-screen, safe-area, botones 44px, scroll interno, cierre con X/backdrop/ESC | .provider-drawer 100% ancho; header/body/footer con safe-area; .provider-drawer__close 44px |
| 16 | Cotizaciones | Modal nueva cotización: campos en 1 columna; footer sticky con botones grandes | .quot-modal__foot sticky; .btn min-height 48px |
| 17 | **Generar factura** | **Conceptos en cards**; **IVA/retenciones compactos**; **botones 44px** | .items--cards; .tax-global compacto @media 390px; .action-bar .btn min-height 44px |
| 18 | Generar factura | Barra de acción inferior (Enviar/Guardar) accesible; no tapada por teclado virtual | .action-bar fixed bottom; padding safe-area |

**Resumen técnico 390px:** Cero scroll horizontal (overflow-x: clip/hidden en cadena). Emitidas/Recibidas: resumen fijo arriba, lista de facturas en cards con scroll solo en .card__body. Generar factura: conceptos en cards, IVA/retenciones compactos, botones 44px. Drawer proveedores: full-screen, safe-area, 44px touch targets.

---

## 768px (tablet / ventana estrecha)

| # | Página / Área | Check | Estado |
|---|----------------|-------|--------|
| 1 | Global | Sidebar sigue siendo drawer (o colapsable); topbar completa | Comportamiento igual que 390px o sidebar fijo según diseño |
| 2 | Home | Mitad izquierda/derecha (métricas vs factura rápida) puede seguir en 2 columnas o pasar a 1 | .dashboard-half-row 1fr en 768px |
| 3 | Emitidas / Recibidas | Tabla visible con scroll horizontal **solo dentro** del card; o seguir en cards según breakpoint | 640px breakpoint: cards; ≥641px tabla |
| 4 | Cotizaciones | Modal cotización: tabla de conceptos puede ser tabla compacta o filas; footer sticky | .quot-modal__body padding-bottom para footer |
| 5 | Proveedores | Drawer "Ver facturas" con ancho cómodo (ej. 90vw o 400px); en ≤390px full-screen | .ui-drawer max-width en 768px; @media 390px width 100% |

---

## Resumen de breakpoints usados

- **390px:** Cero scroll horizontal (portal, main, ym-card); resumen Emitidas/Recibidas no deslizable, métricas en wrap; lista facturas scroll interno; drawer proveedores full-screen + safe-area + 44px; form conceptos/IVA compactos y botones 44px.
- **480px:** Padding global 12/16px; card header/body; form action-bar en columna; concept-card padding; botones 44px.
- **640px:** Emitidas/Recibidas: cambio a lista en cards; ocultar tabla; paginación más espaciada; layout flex resumen fijo + lista con scroll.
- **768px:** Dashboard en 1 columna; touch targets 44px; modales y drawer full-width o max-width controlado; cotizaciones footer sticky.
- **1024px:** Formulario generar factura: columnas de conceptos (3 cols); antes en 768px ya en 2 cols.

---

## Cómo validar sin DevTools (dispositivo real)

1. En el móvil, abrir el portal (misma red que el servidor o túnel).
2. Comprobar que al abrir **Emitidas** o **Recibidas** se ve la lista en cards, no tabla ancha.
3. Pulsar "Sync SAT" en la barra de la lista y comprobar toast "Sync iniciado" y estado "En proceso…".
4. Ir a **Clientes** sin datos: debe verse "Aún no tienes clientes" y botón "Crear primer cliente".
5. Navegar por el menú (hamburguesa) y comprobar que el ítem activo se resalta.

Si todo lo anterior se cumple en 390px y 768px, el checklist móvil está cubierto.
