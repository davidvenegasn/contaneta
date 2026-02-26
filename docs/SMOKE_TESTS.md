# Smoke tests — ContaNeta

Pasos manuales y scripts para verificar que el portal responde y las rutas clave no devuelven 500 ni pantallas blancas.

---

## 1. Script automático (sin token)

**Requisito:** Servidor corriendo (ej. `./run_server.sh` o `uvicorn app:app --port 8000`).

```bash
./scripts/smoke_portal.sh
# o con base URL distinta:
BASE_URL=http://127.0.0.1:9000 ./scripts/smoke_portal.sh
```

Comprueba: `/health`, `/ready`, `/`, `/login`, `/signup`, `/portal/home`, `/portal/info`, `/portal/invoices/issued`, `/portal/invoices/received`, `/portal/convertir-edo-cuenta`, `/portal/summary`. Para rutas que requieren sesión se acepta 200, 302 o 401. Si la respuesta es 200, se verifica que el cuerpo no esté vacío y que contenga marcadores HTML esperados (`<title`, `<html`, `csrf-token` o `portal`) para evitar pantallas blancas.

---

## 2. Script con token (API + portal)

Para probar rutas que requieren sesión (portal home, API clientes/productos):

```bash
# Token debe existir en issuer_tokens y apuntar a un issuer válido (ej. demo)
export PORTAL_SMOKE_TOKEN=demo
export BASE_URL=http://127.0.0.1:8000
python3 scripts/smoke_selfserve.py
```

---

## 3. Prueba manual guiada

Hacer estas comprobaciones en el navegador (o con curl/DevTools) para validar flujos críticos.

### 3.1 Inicio

1. Abrir `BASE_URL/` → debe redirigir a `/portal/home` (o a `/login` si no hay cookie).
2. Abrir `BASE_URL/login` → debe mostrar formulario de login (HTML con "Iniciar sesión" o similar).
3. Si tienes token: `BASE_URL/login?token=TU_TOKEN` → debe redirigir y dejar cookie; luego `/portal/home` debe mostrar el dashboard (Inicio, Factura rápida, etc.).

### 3.2 Facturas emitidas / recibidas

1. Con sesión válida: ir a **Facturas → Emitidas** (o `/portal/invoices/issued`).
2. Debe cargar la página (mes selector, tabla o empty state). No 500 ni pantalla blanca.
3. Igual para **Facturas → Recibidas** (`/portal/invoices/received`).
4. Opcional: abrir detalle de un CFDI (drawer o página) y comprobar que se muestran UUID, PDF/XML.

### 3.3 Movimientos (bancos)

1. Con sesión: **Bancos** o ruta de movimientos (ej. `/portal/bank/movements` o la que corresponda al menú).
2. Debe cargar listado o empty state. No 500.

### 3.4 Bancos — upload

1. Ir a la página de subir estado de cuenta (convertir PDF a Excel o similar).
2. Subir un PDF pequeño de prueba (si existe fixture). Debe validar extensión y tamaño; no 500 por path traversal ni por archivo grande.
3. Si no hay PDF de prueba, al menos comprobar que el formulario carga y que al enviar sin archivo (o con tipo incorrecto) devuelve 400 con mensaje claro.

### 3.5 Resumen

1. Ir a **Resumen** (o `/portal/summary`).
2. Debe cargar la página (gráficos o tablas por mes). No 500.

### 3.6 Health y listas API

- `GET /health` → 200, JSON con `db_readable`, `migrations_applied`.
- Con cookie de sesión: `GET /api/customers`, `GET /api/products` → 200 y JSON con `items` (o array).

---

## 4. Qué considerar “fallo”

- **500** en cualquier ruta pública o del portal que se use en el flujo anterior.
- **Pantalla blanca** (HTML vacío o sin estructura esperada) donde debería verse contenido.
- **404** en rutas que existen según la documentación (ej. `/portal/home`, `/login`).
- **Health** sin `db_readable` o sin `migrations_applied` en entorno con DB y migraciones aplicadas.

---

## 5. Tests automatizados (pytest)

Si existe `tests/` y pytest configurado:

- Test de import: `import app`, `import config`, `import database` (sin errores).
- Test de health: cliente TestClient `GET /health` → 200 y campos esperados.
- Opcional: test de que una ruta HTML del portal devuelve 200 o 302 y contenido no vacío.

Los scripts `smoke_portal.sh` y `smoke_selfserve.py` son complementarios a pytest: cubren arranque real y cookies/redirects.
