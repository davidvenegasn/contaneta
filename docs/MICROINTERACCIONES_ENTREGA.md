# Micro-interacciones tipo “app premium” — Entrega

## API global

- **`window.uiToast({ type, title, message, timeout })`**  
  - `type`: `'success' | 'error' | 'danger' | 'info' | 'warning'`  
  - `timeout`: opcional, ms (por defecto 3200; error/danger 5000).

- **`window.uiToastError(err, title, message)`**  
  Muestra toast de error a partir de un error o mensaje.

- **`window.uiSetButtonLoading(btn, loading, loadingText?)`**  
  Pone o quita estado loading en un botón (spinner + disabled).  
  `loadingText` por defecto: `'Cargando…'`.

- **`window.uiSkeletonTableRows(cols, rows)`**  
  Devuelve HTML de filas skeleton para un `<tbody>` (colspan = cols, una fila por cada row).

- **`window.uiSuccessOverlay({ title, message, actions, copyLink, copyLabel })`**  
  - `actions`: `[{ label, href }]` o `[{ label, onClick }]`.  
  - `copyLink`: texto a copiar al portapapeles (ej. link de cotización).  
  - `copyLabel`: texto del botón “Copiar” (default: “Copiar link”).  
  - Checkmark animado con SVG; animación desactivada con `prefers-reduced-motion: reduce`.

- **`window.uiSuccessOverlayClose()`**  
  Cierra el overlay si está abierto.

---

## Archivos modificados / creados

| Archivo | Cambios |
|--------|--------|
| **static/css/components.css** | Toasts (stack + variante `toast--info`), skeleton-table, `.btn--loading` + `.btn__spinner` (y `@media (prefers-reduced-motion)`), Success Overlay (backdrop, card, icon checkmark animado, acciones). |
| **static/js/ui.js** | Nuevo. Implementa `uiToast`, `uiToastError`, `uiSetButtonLoading`, `uiSkeletonTableRows`, `uiSuccessOverlay`, `uiSuccessOverlayClose`. |
| **templates/base_portal.html** | Carga de `/static/js/ui.js`; wrapper de `portalToast` para aceptar `timeout` y `type: 'error'`; bloque `#demoUiHooks` (oculto) + script que con `?demo=1` muestra botones de simulación; estilos `.demo-ui-hooks`. |
| **templates/portal_issued.html** | Al cargar la tabla usa `uiSkeletonTableRows(9, 5)` para mostrar 5 filas skeleton. |
| **templates/portal_received.html** | Igual: `uiSkeletonTableRows(9, 5)` al cargar. |
| **templates/portal_clients.html** | Guardar cliente: `uiSetButtonLoading(saveBtn, true/false)`, `uiToast` / `uiToastError` (con fallback a `portalToast`). |
| **templates/portal_products.html** | Guardar producto: `uiSetButtonLoading`, `uiToast` / `uiToastError`. |
| **templates/portal_quotations.html** | Guardar/enviar: `uiSetButtonLoading` en ambos botones; al enviar y obtener `public_token` se llama a `uiSuccessOverlay` con “Copiar link” y acción “Ver cotizaciones” (si no hay `uiSuccessOverlay`, se usa el modal de link existente). |
| **templates/success.html** | Pasa a extender `base_portal.html`; al cargar llama a `uiSuccessOverlay` con título “Factura emitida”, mensaje con total, acciones Descargar PDF, Descargar XML y “Crear otra factura” (usa `uuid` cuando existe). Fallback en texto + enlaces si no hay `uiSuccessOverlay`. |

---

## Cómo probarlo manualmente

1. **Toasts**  
   - Añadir `?demo=1` a cualquier URL del portal (ej. `/portal?demo=1`).  
   - Aparecen los botones “Simular éxito”, “Simular error”, “Simular info” abajo a la derecha.  
   - Probar cada uno y comprobar que se muestra el toast correspondiente.

2. **Success Overlay (demo)**  
   - Con `?demo=1`, pulsar “Simular overlay”.  
   - Debe mostrarse el overlay con checkmark, título “Cotización creada”, “Copiar link” y “Ver cotización”.

3. **Loading en botones**  
   - **Clientes:** Portal → Clientes → Nuevo cliente → rellenar y Guardar. El botón debe mostrar “Guardando…” y spinner.  
   - **Productos:** Portal → Productos → Agregar producto → Guardar. Igual.  
   - **Cotizaciones:** Nueva cotización → cliente + conceptos → “Guardar borrador” o “Enviar y obtener link”. El botón correspondiente debe mostrar “Guardando…” / “Enviando…” y spinner.

4. **Skeleton en tablas**  
   - Portal → Facturas emitidas o Facturas recibidas. Al cargar la página se ven 5 filas skeleton hasta que llegan los datos.

5. **Success Overlay en flujos reales**  
   - **Cotización:** Nueva cotización → Enviar y obtener link. Al terminar debe abrirse el overlay con “Copiar link” y “Ver cotizaciones”.  
   - **Factura:** Generar una factura hasta llegar a la página de éxito. Debe mostrarse el overlay con “Factura emitida”, total, Descargar PDF, Descargar XML y “Crear otra factura”.

6. **Accesibilidad**  
   - Con “Reducir movimiento” activado en el SO, el checkmark del overlay no debe animarse (stroke-dashoffset fijo).  
   - El spinner del botón en `prefers-reduced-motion: reduce` deja de girar (estilo alternativo).

---

## Resumen

- Toasts globales con **success / error / info** y API `window.uiToast` / `window.uiToastError`.  
- **Skeleton** de 5 filas en tablas de Emitidas y Recibidas.  
- **Botones con loading** (spinner) en guardar cliente, producto y cotización.  
- **Success Overlay** reutilizable con checkmark animado (respetando `prefers-reduced-motion`), texto y acciones (Descargar PDF/XML, Copiar link, etc.).  
- Integración en: crear/guardar cliente, crear producto, crear/enviar cotización (y copiar link), y página de factura emitida.  
- **Demo:** `?demo=1` en el portal muestra botones para simular toasts y overlay.
