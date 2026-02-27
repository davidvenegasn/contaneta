# Rendimiento del portal (Frontend)

Objetivo: que el portal se sienta rápido en un portátil normal. Cambios medibles: menos requests al escribir, UI más fluida, menos reflows.

---

## 1. Reflows en tablas: debounce en búsqueda

**Problema:** En listados (Clientes, Productos, Proveedores), cada tecla en el input de búsqueda ejecutaba `filter()` y reemplazaba todo `tbody.innerHTML`, provocando layout y pintura en cada keystroke.

**Cambio:** Debounce de **250 ms** en el evento `input` del buscador. Solo se ejecuta `filter()` (y por tanto `render()`) cuando el usuario deja de escribir al menos 250 ms.

**Dónde:**
- `templates/portal_clients.html`: `searchEl.addEventListener('input', ...)` → `clearTimeout(filterDebounce); filterDebounce = setTimeout(filter, 250);`
- `templates/portal_products.html`: mismo patrón, 250 ms.
- `templates/portal_providers.html`: mismo patrón, 250 ms.
- Cotizaciones no tiene búsqueda en el listado; solo se aplica límite de filas y paginación.

**Resultado:** Menos reflows al escribir; la UI no se recalcula en cada tecla.

---

## 2. Búsquedas SAT (ProdServ / Unidad): debounce + cancelación

**Problema:** Las búsquedas al catálogo SAT (ProdServ, y en el formulario de factura también Unidad) se disparaban por tecla y las peticiones anteriores podían llegar después que las nuevas, generando requests innecesarios y posibles parpadeos.

**Cambios:**
- **Debounce 250 ms** (antes 300 ms en algunos sitios): una sola petición por “racha” de tecleo.
- **AbortController:** Antes de cada `fetch` se aborta la petición anterior (`controller.abort()`). La nueva petición usa `fetch(..., { signal })`. Si la respuesta llega tras abortar, se ignora (`AbortError`).

**Dónde:**
- `templates/portal_products.html`: `searchProdserv()` con `prodservAbort = new AbortController()`, `fetch(..., { signal })`, debounce **250 ms** en `keyEl.addEventListener('input', ...)`.
- `templates/portal_home.html`: `searchQuickProdserv()` con `quickProdservAbort`, `fetch(..., { signal })`, debounce **250 ms** en `quickProdKey.addEventListener('input', ...)`.
- `templates/form/_script_form.html`: `searchProdserv()` con `_prodservAbort`, `fetch(..., { signal })`, y `DEBOUNCE_CATALOG_MS = 250` (antes 300). El input del modal ProdServ usa `debounce(() => searchProdserv(input.value), DEBOUNCE_CATALOG_MS)`.

**Resultado:** Menos peticiones al escribir; solo cuenta la última búsqueda; la UI no se actualiza con resultados obsoletos.

---

## 3. Límite de 200 filas y paginación simple (sin virtualización)

**Enfoque:** Sin librerías de virtualización. Se limita la cantidad de filas mostradas a **200 por página** y, si hay más, se muestra paginación simple (Anterior / Siguiente).

**Dónde:**
- **Clientes** (`portal_clients.html`): `ROWS_PAGE_LIMIT = 200`, `clientPage`, `lastFilteredRows`. `render(rows)` hace `displayRows = rows.slice(start, start + ROWS_PAGE_LIMIT)`. Bloque `#custTablePagination` con “Mostrando X–Y de N” y botones Anterior/Siguiente.
- **Productos** (`portal_products.html`): mismo esquema, `#prodTablePagination`.
- **Proveedores** (`portal_providers.html`): mismo esquema, `#provTablePagination`.
- **Cotizaciones** (`portal_quotations.html`): mismo esquema, `#quotTablePagination`.

**Emitidas / Recibidas:** Siguen usando **paginación en servidor** (`per_page` en la API, máx. 200 en `routers/api.py`: `Query(50, ge=1, le=200)`). No se cambia el límite por defecto (50); el front ya usa paginación.

**Resultado:** En listados con muchos registros solo se renderizan 200 filas por página; menos DOM y menos trabajo de layout/pintura.

---

## 4. CSS: contain y sombras en listas

**Contain en tablas:**
- `.table-wrap`: se añade `contain: layout paint` para acotar layout y pintura al bloque de la tabla y reducir impacto en el resto de la página.
- `.card--invoice-list .table-wrap`: mismo `contain: layout paint`.

**Sombras en listas grandes:**
- Cards que contienen `.table-wrap` y `.card--invoice-list` usan una sombra más ligera:
  - Normal: `box-shadow: 0 1px 3px rgba(0,0,0,.06), 0 1px 2px rgba(0,0,0,.04);`
  - Hover: `box-shadow: 0 2px 8px rgba(0,0,0,.07), 0 1px 3px rgba(0,0,0,.05);`
- Así se reduce el coste de repintado al hacer scroll en listas grandes.

**Dónde:** `static/css/portal.css`: reglas para `.table-wrap`, `.card--invoice-list .table-wrap`, `.card:has(.table-wrap)` y `.card--invoice-list` (sombra), y `.table-pagination`.

---

## 5. Resumen de valores

| Concepto              | Valor  | Ubicación |
|-----------------------|--------|-----------|
| Debounce búsqueda listado | 250 ms | portal_clients, portal_products, portal_providers |
| Debounce ProdServ/Unidad   | 250 ms | portal_products, portal_home, form/_script_form (DEBOUNCE_CATALOG_MS) |
| Límite filas por página (client-side) | 200 | ROWS_PAGE_LIMIT en clientes, productos, proveedores, cotizaciones |
| per_page máx. API (emitidas/recibidas) | 200 | routers/api.py Query(50, ge=1, le=200) |

---

## 6. Cómo comprobar

- **Debounce:** Escribir rápido en el buscador de Clientes/Productos/Proveedores: el listado no debe actualizarse en cada tecla sino al dejar de escribir ~250 ms.
- **ProdServ:** En “Agregar producto” o en el modal ProdServ del formulario de factura, escribir en la clave: en Network solo deberían verse 1–2 peticiones por racha y, al seguir escribiendo, las anteriores pueden aparecer como (canceled) si el navegador lo muestra.
- **Paginación:** Con más de 200 clientes/productos/proveedores/cotizaciones, debe aparecer “Mostrando 1–200 de N” y botones Anterior/Siguiente.
- **CSS:** Inspeccionar `.table-wrap` y ver `contain: layout paint`; las cards de listados con tabla con sombra más suave.
