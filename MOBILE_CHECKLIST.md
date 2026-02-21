# Mobile Checklist — 390px / 768px

Validación de que el portal es usable y demostrable en móvil sin scroll lateral ni elementos encimados.

**Cómo probar:** DevTools → Toggle device toolbar (Ctrl+Shift+M / Cmd+Shift+M); elegir 390×844 (iPhone 14) o 768×1024 (iPad); recargar y recorrer cada sección.

---

## 390px (móvil estrecho)

| # | Página / Área | Check | Estado |
|---|----------------|-------|--------|
| 1 | Global | Sin scroll horizontal en ninguna vista | body/main con overflow-x: hidden |
| 2 | Global | Padding lateral 12–16px (no contenido pegado al borde) | .main, .main-inner, .card__body en @media 480px |
| 3 | Global | Topbar con título e icono legibles; menú usuario accesible | .portal-topbar__text con max-width; .topbar-user táctil |
| 4 | Global | Sidebar drawer: abre con hamburguesa; cierra con X o backdrop; transición suave | .sidebar, .sidebar-backdrop |
| 5 | Global | Botones y enlaces con min-height/área ≥44px | .btn, .nav-item, .filters-toggle en @media 768px |
| 6 | Home | Cards de métricas y bloques apilados en 1 columna | .dashboard-metrics 1fr; .dashboard-half-row 1fr |
| 7 | Home | Factura rápida: selects y botón "Generar factura" full-width si aplica | .quick-invoice-actions .btn width 100% |
| 8 | Home | Empty states y CTAs (onboarding) con targets táctiles | .onboarding-checklist__item a con min-height 44px |
| 9 | Emitidas / Recibidas | Lista en **cards** (no tabla); cada factura = card con fecha, nombre, concepto, total, estatus | .invoice-list-mobile visible; .table-wrap oculto |
| 10 | Emitidas / Recibidas | Acciones por factura: Detalle, XML, PDF en fila inferior de la card; botones táctiles | .invoice-card-mobile__actions con .btn flex 1, min-height 44px |
| 11 | Emitidas / Recibidas | Barra Sync: "Último sync" en una línea; botón Sync solo icono | .list-sync-bar__btn-label display none; .list-sync-bar__meta max-width 140px |
| 12 | Emitidas / Recibidas | Filtros: panel colapsable; inputs y selects usables | .filters-panel; inputs con altura 46px |
| 13 | Clientes / Productos / Proveedores | Tabla con scroll horizontal **contenido** en .table-wrap (o en 390px ocultar tabla y mostrar lista si existiera) | En 390px se mantiene tabla en wrap; o se usa solo empty state / listado simple |
| 14 | Clientes / Productos / Proveedores | Empty state y bloque "No se pudo cargar" legibles; botón Reintentar táctil | .empty-state, .btn min-height 44px |
| 15 | Cotizaciones | Modal nueva cotización: campos en 1 columna; footer sticky con botones grandes | .quot-modal__foot sticky; .btn min-height 48px |
| 16 | Generar factura | Secciones y conceptos en cards/filas apiladas; sin encimes | form.css item-row-top 1 col; concept-card 1 col |
| 17 | Generar factura | Barra de acción inferior (Enviar/Guardar) accesible; no tapada por teclado virtual | .action-bar fixed bottom; padding safe-area |

**Nota:** En 390px las tablas de Clientes/Productos/Proveedores pueden seguir siendo tabla con scroll horizontal dentro de .table-wrap; el requisito es que **no** haya scroll horizontal en body. Si en algún momento se implementa vista en cards para esas listas en móvil, se puede marcar aquí.

---

## 768px (tablet / ventana estrecha)

| # | Página / Área | Check | Estado |
|---|----------------|-------|--------|
| 1 | Global | Sidebar sigue siendo drawer (o colapsable); topbar completa | Comportamiento igual que 390px o sidebar fijo según diseño |
| 2 | Home | Mitad izquierda/derecha (métricas vs factura rápida) puede seguir en 2 columnas o pasar a 1 | .dashboard-half-row 1fr en 768px |
| 3 | Emitidas / Recibidas | Tabla visible con scroll horizontal **solo dentro** del card; o seguir en cards según breakpoint | 640px breakpoint: cards; ≥641px tabla |
| 4 | Cotizaciones | Modal cotización: tabla de conceptos puede ser tabla compacta o filas; footer sticky | .quot-modal__body padding-bottom para footer |
| 5 | Proveedores | Drawer "Ver facturas" con ancho cómodo (ej. 90vw o 400px) | .ui-drawer max-width en 768px |

---

## Resumen de breakpoints usados

- **390px:** Ajustes específicos en algunos bloques (ej. .list-sync-bar__meta).
- **480px:** Padding global 12/16px; card header/body; form action-bar en columna; concept-card padding.
- **640px:** Emitidas/Recibidas: cambio a lista en cards; ocultar tabla; paginación más espaciada.
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
