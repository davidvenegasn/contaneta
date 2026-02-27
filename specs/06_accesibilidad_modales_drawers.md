# Spec: Accesibilidad básica de modales y drawers

**ID:** `SPEC-06`  
**Origen:** AUDIT_README.md — UX, Job 11 (accesibilidad)  
**Prioridad:** Baja

---

## Objetivo

Mejorar la accesibilidad básica de modales y drawers del portal: focus trap (el foco no sale del modal/drawer con Tab hasta cerrar), cierre con tecla Escape, y anuncio de toasts y mensajes de error para lectores de pantalla (aria-live o role="alert"). Botones e iconos sin texto visible deben tener aria-label.

---

## Alcance

- Modales en `templates/base_portal.html`: factura rápida, agregar cliente, agregar producto, selector ProdServ/Unidad, modal de sesión expirada, y cualquier otro modal que se abra desde el portal.
- Drawers: detalle CFDI (emitidas/recibidas), drawer de proveedores (lista de facturas por proveedor).
- Al abrir modal/drawer: mover el foco al primer elemento focusable (input, botón) y mantener el foco dentro del contenedor (focus trap) hasta que el usuario cierre con botón, Escape o clic en backdrop.
- Al cerrar: devolver el foco al elemento que abrió el modal/drawer (o al cuerpo de la página si no es posible).
- Toasts y bloques de load-error: asegurar `aria-live="polite"` (toasts) o `role="alert"` (errores críticos) para que los lectores de pantalla anuncien el mensaje.
- Botones que solo muestran icono (lápiz, cerrar, copiar UUID): tener `aria-label` descriptivo.

---

## Fuera de alcance

- Cumplimiento completo de WCAG 2.1 AA en toda la aplicación.
- Cambios en el diseño visual de modales/drawers.
- Navegación solo por teclado de toda la app (solo se exige dentro del modal/drawer y cierre con Escape).
- Soporte específico para otros dispositivos de asistencia más allá de lectores de pantalla y teclado.

---

## Archivos a tocar

| Archivo / directorio | Cambio previsto |
|----------------------|-----------------|
| `templates/base_portal.html` | En cada modal: al abrir, focus al primer focusable; implementar focus trap (Tab/Shift+Tab ciclan dentro del modal); al cerrar, devolver foco al trigger. Añadir listener keydown Escape para cerrar. Verificar aria-label en botones de cerrar e iconos. |
| `static/js/ui.js` (o script en base_portal) | Función reutilizable para focus trap (o integrar en la lógica de apertura/cierre de modales). Listener Escape global o por modal. |
| Drawers (detalle CFDI, proveedores) | Misma lógica: focus al abrir, focus trap, Escape cierra, foco de vuelta al trigger al cerrar. |
| Bloques de load-error (`portal_load_error`) | Verificar que el contenedor tenga `aria-live="polite"` o `role="alert"` para anuncio. |
| Toasts | Verificar que el contenedor de toasts tenga `aria-live="polite"`. |
| Botones/iconos sin texto (editar, cerrar, copiar UUID) en listados y modales | Añadir `aria-label` con texto descriptivo (ej. "Editar", "Cerrar", "Copiar UUID"). |

---

## Reglas

1. **Focus trap:** Dentro del modal/drawer, Tab debe mover el foco al siguiente elemento focusable dentro del mismo; si el foco está en el último elemento, Tab debe llevarlo al primero. Shift+Tab a la inversa. No se permite que Tab salga del contenedor hasta cerrar.
2. **Escape:** La tecla Escape cierra el modal/drawer activo (y restaura foco al trigger). Si hay varios modales apilados, Escape cierra el superior.
3. **Foco al abrir:** Al mostrar el modal/drawer, el foco debe ir al primer elemento interactivo (input, botón). Si el modal es solo informativo, al botón "Cerrar" o equivalente.
4. **Foco al cerrar:** Al cerrar, devolver el foco al elemento que abrió el modal (ej. botón "Nueva factura") para que el usuario pueda seguir navegando por teclado.
5. **Anuncios:** Los toasts y el bloque de error de carga deben estar en un contenedor con `aria-live="polite"` (toasts) o `role="alert"` (errores que requieren atención), para que lectores de pantalla los anuncien.
6. **aria-label:** Todo control que solo muestre un icono debe tener `aria-label` con el propósito (ej. "Editar movimiento", "Copiar UUID", "Cerrar").

---

## Criterios de aceptación

- [ ] En cada modal del portal, al abrirlo el foco va al primer elemento focusable y Tab/Shift+Tab no sacan el foco del modal hasta cerrarlo.
- [ ] La tecla Escape cierra el modal o drawer abierto y restaura el foco al elemento que lo abrió.
- [ ] Al cerrar el modal/drawer (botón, Escape o backdrop), el foco vuelve al trigger.
- [ ] Los toasts se anuncian con aria-live (contenedor con `aria-live="polite"`).
- [ ] El bloque de load-error tiene `role="alert"` o `aria-live="assertive"` para que se anuncie el error.
- [ ] Los botones e iconos sin texto visible en listados y modales tienen `aria-label` descriptivo.
- [ ] Probado con teclado (Tab, Shift+Tab, Enter, Escape) y, si es posible, con un lector de pantalla (VoiceOver/NVDA) para verificar anuncios.

---

## Cómo probarlo manualmente

1. **Focus trap:** Abrir el modal de factura rápida (o agregar cliente). Pulsar Tab varias veces; el foco debe circular por los elementos del modal y no saltar al contenido de fondo. Pulsar Escape; el modal debe cerrarse y el foco volver al botón que lo abrió.
2. **Escape:** Abrir drawer de detalle CFDI. Pulsar Escape; debe cerrarse el drawer.
3. **Foco al abrir:** Abrir "Agregar cliente"; el foco debe estar en el primer campo (RFC o nombre) o en el primer botón.
4. **Toasts:** Disparar un toast (ej. guardar cliente). Con lector de pantalla activado, verificar que se anuncie el mensaje (el contenedor de toasts debe tener aria-live).
5. **Load-error:** Provocar un error de carga en una lista; verificar que el bloque de error tenga role="alert" o aria-live y que el lector anuncie el mensaje.
6. **aria-label:** En una lista (emitidas/recibidas), enfocar el botón de copiar UUID o editar; el lector debe anunciar "Copiar UUID" o "Editar" (o el label definido).

---

## Referencias

- AUDIT_README.md — Sección 4.3 (Modales y drawers), Job 11.
- PORTAL_AUDITORIA_MEJORAS.md — Referencias a focus trap y ESC.
- templates/base_portal.html — Modales y drawers.
