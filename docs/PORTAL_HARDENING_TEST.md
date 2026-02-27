# Plan de prueba manual — Portal Hardening

Comprobar que el pack de endurecimiento del portal funciona sin regresiones. Ejecutar tras cambios en errores backend, fetch con timeout, sesión expirada, componentes UI y Support Snapshot.

---

## 1. Portal home

- Abrir `/portal` (o `/portal/home`).
- Comprobar que carga sin errores en consola.
- Si hay demo/issuer: ver que los accesos rápidos (clientes, productos, factura rápida) están disponibles.

## 2. Timeout y Reintentar (clientes)

- Ir a **Clientes** (`/portal/clients`).
- En DevTools → Network: activar **throttling** (Slow 3G o custom muy lento).
- Recargar la página o disparar la carga de datos.
- Debe aparecer tras ~30 s un mensaje de error de carga con botón **Reintentar**.
- Quitar throttling y pulsar Reintentar: la lista debe cargar.

## 3. Sesión expirada (401)

- Con el portal abierto, en DevTools → Application → Cookies: borrar la cookie de sesión (`portal_session` o la que use la app).
- Disparar cualquier petición que requiera auth (recargar lista, guardar, etc.).
- Debe mostrarse el **modal "Sesión expirada"** y no quedar overlays colgados.
- El botón "Iniciar sesión" debe llevar a `/login`.

## 4. Empty state en emitidas/recibidas

- Ir a **Emitidas** y **Recibidas** (con usuario sin datos o con issuer sin CFDI).
- Debe mostrarse el **empty state** (lista vacía), no el bloque de "error de carga".
- Empty = 200 con lista vacía; error = timeout/red/5xx.

## 5. Accesibilidad: ESC y foco en modales

- Abrir un modal (factura rápida, añadir cliente, añadir producto, ProdServ, etc.).
- Pulsar **ESC**: el modal debe cerrarse.
- Con el modal abierto, pulsar **Tab**: el foco debe permanecer dentro del modal (no saltar al contenido de atrás).
- Cerrar modal y comprobar que el foco vuelve de forma coherente.

## 6. Support Snapshot en /status

- Abrir **GET /status** (sin auth).
- Debe mostrarse:
  - Estado del sistema (DB, migraciones, storage).
  - Bloque **"Support Snapshot"** con:
    - DB (archivo): solo nombre, sin ruta completa.
    - Última migración, storage existe/escribible.
    - PHP disponible, reportlab, pdfplumber.
    - ENV, DEV_MODE, hora servidor (UTC).
- No debe aparecer ningún secreto (SESSION_SECRET, rutas completas en prod, etc.).

---

## Definición de listo

- Cambios aplicados sin romper rutas existentes.
- Timeout + Reintentar visibles en listados bajo red lenta.
- 401 muestra modal de sesión expirada y cierra overlays.
- Empty state correcto en listas vacías; load error solo en fallo de petición.
- ESC cierra modales; Tab mantiene foco dentro del modal.
- `/status` muestra Support Snapshot con información útil y sin secretos.
