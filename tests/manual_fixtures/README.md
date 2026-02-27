# Fixtures manuales para desarrollo UI

Carpeta con respuestas JSON típicas de la API para probar el portal **sin depender del backend ni SAT/DB**.

## Uso

1. Activa el modo fixtures en desarrollo:
   ```bash
   export DEV_FIXTURES=1
   # o en .env: DEV_FIXTURES=1
   ```

2. Arranca la app (con sesión/issuer de demo si aplica).

3. Las rutas del portal que piden `/api/customers`, `/api/products`, `/api/invoices/issued` o `/api/invoices/received` recibirán estos JSON en lugar de consultar la base de datos.

## Archivos

| Archivo        | Sustituye a              | Estructura                          |
|----------------|--------------------------|-------------------------------------|
| `clients.json` | `GET /api/customers`     | `{ "items": [...], "total": N }`    |
| `products.json`| `GET /api/products`      | `{ "items": [...], "total": N }`    |
| `issued.json`  | `GET /api/invoices/issued` | `{ "data": [...], "pagination": {...}, "filters": {...} }` |
| `received.json`| `GET /api/invoices/received` | Igual que issued                    |

## Editar datos

Puedes modificar los JSON para añadir más filas, cambiar totales o paginación y probar empty state, paginación o errores. La estructura debe coincidir con la que devuelve la API real para que la UI no falle.

## Seguridad

- Solo tiene efecto con `DEV_FIXTURES=1`. En producción no se usa.
- No incluir datos reales (RFC, nombres, UUID de CFDI reales) si el repo es público.
