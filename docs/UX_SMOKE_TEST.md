## UX Smoke Test (5 min)

### Objetivo
Detectar regresiones típicas de UI (modales “abajo”, scroll del fondo, gaps inconsistentes) en pocos minutos antes de deploy.

### Pre-requisitos
- Estar logueado en el portal.
- Usar viewport desktop y luego probar una vez en móvil (o achicar ventana).

### Checklist (modales)
- **Productos**
  - Ir a `/portal/products`
  - Click **“Nuevo producto”**
  - Verificar:
    - Modal centrado con overlay (no aparece “abajo” en la página)
    - Scroll de fondo bloqueado mientras el modal está abierto
    - Cierra con **ESC**
    - Cierra al click en el overlay/backdrop
- **Proveedores**
  - Ir a `/portal/providers`
  - Click **“Agregar proveedor”**
  - Verificar lo mismo (centrado, overlay, ESC, backdrop, scroll bloqueado)
- **Cotizaciones**
  - Ir a `/portal/quotations`
  - Click **“Nueva cotización”**
  - Verificar lo mismo
  - Dentro del modal, probar que “Cancelar”/“Cerrar” cierran y vuelves a la página sin “scroll trabado”

### Checklist (layout / gap sidebar↔contenido)
- Abrir estas páginas y confirmar que el contenido inicia alineado (mismo gutter):
  - `/portal/home`
  - `/portal/invoices/issued`
  - `/portal/invoices/received`
  - `/portal/contacts`
  - `/portal/products`
  - `/portal/quotations`
  - `/portal/summary`
  - `/portal/create`
- Si una página se ve “pegada” o “corrida”, buscar wrappers que se salgan del layout (ej. `width:100vw`) en lugar de parchar con padding local.

### Checklist (Factura rápida)
- En `/portal/home`:
  - Abrir **Factura rápida** y abrir el preview
  - Verificar que el modal del preview mantiene el estilo (sin CSS inline) y cierra correctamente.

