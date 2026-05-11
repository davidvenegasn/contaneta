# Notas finales — Demo móvil estable (MEGA CONTRATO)

**Objetivo:** Cerrar Must A2/A4, reparar Home Factura rápida y dejar demo móvil estable (empty states, 390px, drawer proveedores pro).

---

## Qué se arregló

### Must
- **A2 — SESSION_SECRET:** En `ENV=prod` el arranque exige `SESSION_SECRET` en `.env` (o muestra log CRITICAL con instrucciones). Documentado en `.env.example`, `LAUNCH_CHECKLIST.md` y `DEPLOY_GUIDE.md`. `/health` no expone secretos.
- **A4 — FIEL post-upload:** Tras guardar credenciales SAT se ejecuta validación (`check_fiel.php`); se persisten `validation_ok` y `validation_message` y se muestran en el panel ("FIEL válida ✓" o error legible). Botón "Validar de nuevo" en portal Configuración SAT.

### Home — Factura rápida
- "+ Añadir cliente" y "+ Añadir producto" abren modal, guardan vía `/api/customers/create` y `/api/products/create`, refrescan el dropdown y seleccionan el nuevo. Si no hay clientes/productos se muestra hint/empty state con CTA. Se añadió `credentials: 'same-origin'` a los fetch de creación para asegurar envío de cookie.

### Should (demo móvil)
- **B3/B6 — Empty states y un solo error:** Listas (clientes, productos, proveedores, cotizaciones, emitidas, recibidas) con API 200 + `[]` muestran empty state; "No se pudo cargar" solo cuando `res.ok === false`. En el drawer de facturas del proveedor se eliminó el toast duplicado: solo se muestra el bloque de error en el panel.
- **B4/B5 — 390px y drawer proveedores:** Drawer "Ver facturas" tiene overlay full screen, scroll interno en el body, cierre con ESC y focus trap. En móvil 390px el drawer es a pantalla completa y los botones tienen área táctil mínima (44px). Tablas en `.table-wrap` con scroll interno en 390px (`overflow-x: auto`, `-webkit-overflow-scrolling: touch`).

---

## Cómo probar en 10 min

1. **SESSION_SECRET (A2):** En prod, quitar `SESSION_SECRET` del `.env` y arrancar la app → debe aparecer log CRITICAL pidiendo definir el secret. Volver a añadirlo y arrancar → sin warning.
2. **FIEL (A4):** Portal → Ajustes → Configuración SAT. Subir CER/KEY y guardar → debe mostrarse "FIEL válida ✓" o mensaje de error en el panel. Probar "Validar de nuevo".
3. **Factura rápida (Home):** `/portal/home` → en "Factura rápida" clic en "+ Añadir cliente" → rellenar RFC y razón social → Guardar → el select debe actualizarse y seleccionar el nuevo. Igual con "+ Añadir producto". Sin clientes/productos debe verse el hint/empty state.
4. **Empty states:** En Clientes / Productos / Proveedores / Cotizaciones (o Emitidas/Recibidas sin datos), con API devolviendo 200 y lista vacía → debe verse "Aún no tienes…" con CTA, no "No se pudo cargar". Provocar un 401 o 500 en una lista → solo un bloque "No se pudo cargar" con Reintentar, sin toast adicional.
5. **Drawer proveedores:** `/portal/providers` → "Ver facturas" en un proveedor → drawer abre; ESC lo cierra; Tab mantiene el foco dentro del drawer. En viewport 390px el drawer ocupa todo el ancho y los botones son tocables.
6. **Móvil 390px:** Usar DevTools (390×844). Home, Emitidas, Recibidas, Proveedores, Cotizaciones: sin scroll horizontal en body; tablas con scroll solo dentro del contenedor.

Checklist detallado: **QA_MOBILE_SMOKE.md**.
