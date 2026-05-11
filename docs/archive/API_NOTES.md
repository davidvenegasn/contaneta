# Notas de la API (routers/api.py)

API JSON bajo el prefijo `/api`. Autenticación por sesión o token de portal (`get_portal_issuer`).

---

## Paginación y límites por defecto

Para **evitar devolver miles de filas**, todos los listados aplican un **límite por defecto** y aceptan parámetros de paginación cuando aplica.

### Constantes

- **Límite por defecto:** `200` registros.
- **Límite máximo:** `500` registros (los parámetros `limit` y `per_page` están acotados con `le=500`).

### Parámetros de consulta

| Parámetro   | Uso        | Default | Descripción                          |
|------------|------------|--------|--------------------------------------|
| `limit`    | listados   | 200    | Máximo de registros a devolver       |
| `offset`   | listados   | 0      | Registros a saltar (paginación)      |
| `page`     | facturas   | 1      | Número de página (solo emitidas/recibidas) |
| `per_page` | facturas   | 200    | Items por página (solo emitidas/recibidas) |

### Endpoints que usan `limit` y `offset`

- **GET /api/customers** — Lista de clientes (customer_profiles). `limit`, `offset`.
- **GET /api/products** — Lista de productos (issuer_products). `limit`, `offset`.
- **GET /api/quotations** — Lista de cotizaciones. `limit`, `offset`.
- **GET /api/provider-invoices** y **GET /api/providers/invoices** — Facturas recibidas de un proveedor (por `rfc`). `limit`, `offset`. Antes tenían `LIMIT 100` fijo.
- **GET /api/providers** — Lista de proveedores (fusionando supplier_profiles y sat_cfdi). `limit`, `offset`.
- **GET /api/invoices/pending** — Facturas PPD pendientes. `limit`, `offset`. Antes tenían `LIMIT 200` fijo.

### Endpoints que usan `page` y `per_page`

- **GET /api/invoices/issued** — Facturas emitidas (filtros: `ym`, `search`, `status`, etc.). Respuesta incluye `pagination: { page, per_page, total, pages }` y `data`.
- **GET /api/invoices/received** — Facturas recibidas (misma forma). Por defecto `per_page=200`, máximo `500`.

### Formato de respuesta

- **Listados con `limit`/`offset`:** La respuesta sigue siendo un **array** `[...]` (compatibilidad con la UI actual). Solo se limita la cantidad de elementos según `limit` y `offset`.
- **Facturas emitidas/recibidas:** Respuesta con forma `{ "data": [...], "pagination": { ... }, "filters": { ... } }`.

### Resumen

| Endpoint              | Límite por defecto | Máximo | Paginación   |
|-----------------------|---------------------|--------|--------------|
| /api/customers        | 200                 | 500    | limit, offset |
| /api/products         | 200                 | 500    | limit, offset |
| /api/quotations       | 200                 | 500    | limit, offset |
| /api/provider-invoices| 200                 | 500    | limit, offset |
| /api/providers        | 200                 | 500    | limit, offset |
| /api/invoices/pending | 200                 | 500    | limit, offset |
| /api/invoices/issued  | 200 (per_page)      | 500    | page, per_page |
| /api/invoices/received| 200 (per_page)      | 500    | page, per_page |

Los catálogos SAT (`/api/catalogs/forma_pago`, `metodo_pago`, `uso_cfdi`, etc.) y las búsquedas (`/api/catalogs/prodserv`, `/api/catalogs/unidad`) tienen sus propios límites (p. ej. 20–50 ítems) y no usan estas constantes.
