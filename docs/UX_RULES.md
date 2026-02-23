## UX Rules (Portal)

Estas reglas definen el patrón único para **empty / error / success**, y la consistencia visual del portal.

### Regla 1 — Listas: Empty state con CTA (sin toast)

- **Cuándo**: una lista carga correctamente pero está vacía (ej. `[]`, `data.data=[]`).
- **Cómo**:
  - Mostrar un **empty state** dentro del layout normal (card/section).
  - Incluir **1 CTA principal** (ej. “Crear primer cliente”, “Agregar producto”, “Nueva cotización”).
  - No mostrar toast en empty state.
- **Objetivo**: orientar al usuario al siguiente paso, sin “ruido”.

### Regla 2 — Listas: Error block único con Reintentar (sin doble mensaje)

- **Cuándo**: falla una carga por API (red, timeout, \(status \ge 400\), JSON inválido).
- **Cómo**:
  - Mostrar **un solo bloque de error** en la página (no toast + bloque a la vez).
  - El bloque incluye: título breve, mensaje claro y botón **Reintentar**.
  - **Timeout**: el mensaje debe ser explícito (“La solicitud tardó demasiado…”).
  - **401**: disparar modal global **Sesión expirada** y no dejar la UI en estado roto.
- **Objetivo**: recuperación inmediata y consistente.

### Regla 3 — Acciones (crear/guardar/eliminar): Success consistente por tipo

- **Mutaciones importantes** (crear/guardar/eliminar/validar FIEL):
  - Usar **Success Overlay** (`uiSuccessOverlay`) como patrón principal.
  - El overlay debe tener 1 acción (“Entendido”) y opcionalmente una secundaria (“Ver…”, “Ir a…”).
- **Acciones pequeñas** (copiar, switches/toggles):
  - Usar **toast** (`uiToast`) con TTL corto.
- **Errores en acciones**:
  - Usar `uiToastError`/`portalToastError` con mensaje accionable (qué hacer).

---

## Consistencia visual (aplica a todo)

- **Menos inline CSS**: evitar `style=""` en templates; preferir clases en `static/css/portal.css` o `static/css/components.css`.
- **Espaciado/jerarquía**: títulos, subtítulos, cards y botones deben reutilizar componentes/clases existentes.
- **Breadcrumbs**: en pantallas de detalle (CFDI, cotización) siempre mostrar `Inicio > Sección > Detalle`, con el mismo markup y clases.

