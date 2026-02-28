# QA Checklist — UX Hotfix (Home + Contacts)

## Home (`/portal/home`)
- [ ] 1. Three cards visible in grid: "Factura rapida", "Notificaciones", "Acciones rapidas"
- [ ] 2. Factura rapida card has NO scrollbar — inputs and buttons visible without scrolling
- [ ] 3. Notificaciones card has internal scroll when many items — scrollbar is hidden (no grey bar)
- [ ] 4. Acciones rapidas card has NO scrollbar — buttons are visible, clickable, navigate correctly
- [ ] 5. No "Centro de accion" text anywhere — card title says "Notificaciones"

## Clientes (`/portal/clients`)
- [ ] 6. Toolbar shows: [Search input] [+ Añadir cliente (primary)] [Seleccionar varios]
       - "Seleccionar varios" toggles checkboxes + bulk bar with [Emitir a seleccionados] [Borrar seleccionados] [Cancelar]
       - Row actions: 3 icon buttons (pencil=editar, plus-square=facturar, trash=borrar)

## Proveedores (`/portal/providers`)
- [ ] 7. Toolbar shows: [Search input] [+ Agregar proveedor] — NO "Seleccionar varios" button
- [ ] 8. Row actions: 2 icon buttons (pencil=editar, document=ver facturas) — NO bulk checkboxes, NO "Copiar RFCs"
