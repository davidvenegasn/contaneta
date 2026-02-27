# Rail tipo Mindtrip: compacto, expandible, usuario abajo

**ID:** `SPEC-RAIL-MINDTRIP`  
**Origen:** Inspiración Mindtrip (capturas usuario)  
**Prioridad:** Alta

---

## Objetivo

Alinear la barra lateral (rail) del portal con el estilo Mindtrip: rail siempre estrecho por defecto mostrando solo iconos SVG; opción arriba para expandir y ver el nombre de cada página; tooltips al pasar el cursor sobre los iconos cuando está comprimido; y usuario (solo avatar) abajo para abrir el dropdown de cuenta.

---

## Alcance

- **Rail (sidebar izquierdo)** cuando `PORTAL_SHELL_V2=1`:
  - Estado **comprimido** por defecto: ancho fijo (~56px), solo iconos SVG.
  - **Tooltips**: al pasar el ratón sobre un icono (estado comprimido), mostrar un texto con el nombre de la página (ej. "Inicio", "Facturas"), estilo tipo Mindtrip (rectángulo oscuro a la derecha del icono).
  - **Botón “Expandir”** en la parte superior del rail (ej. chevron `>`): al hacer clic, el rail se ensancha y muestra icono + texto (label) de cada ítem. Al hacer clic de nuevo (chevron `<`), se vuelve a comprimir. Persistir preferencia en `localStorage`.
  - **Usuario al final del rail**: un único control (solo avatar/icono, sin nombre) en la parte inferior del rail. Al hacer clic se abre el mismo menú dropdown de usuario (Mi plan, Configuración, Cerrar sesión, etc.). En shell v2 no mostrar el trigger de usuario en la topbar; solo en el rail.
- Ajustes de **CSS y JS** para: ancho expandido, posición del dropdown cuando se abre desde el rail, y accesibilidad (focus, aria-expanded).

---

## Fuera de alcance

- Cambiar el orden de ítems del rail ni la lógica de rutas.
- Rediseñar el contenido del dropdown de usuario (solo cambiar dónde está el trigger en shell v2).
- Modificar el drawer (menú que se abre al clic en la marca); sigue siendo el mismo.

---

## Archivos a tocar

| Archivo | Cambio previsto |
|---------|------------------|
| `templates/components/portal_rail.html` | Botón expandir arriba; labels junto a iconos (visibles solo expandido); bloque usuario abajo (solo avatar). |
| `templates/base_portal.html` | Con shell v2: ocultar trigger de usuario en topbar; exponer `openUserMenu`/`closeUserMenu` para el rail; posicionar dropdown cuando se abre desde el rail. |
| `static/css/portal_shell_v2.css` | Estilos rail expandido (ancho, labels), tooltips, usuario en rail, posición dropdown desde rail. |
| `static/js/portal_shell_v2.js` | Toggle expandir/colapsar rail, persistencia localStorage, clic en usuario del rail para abrir menú. |

---

## Reglas

1. Estado por defecto del rail: **comprimido** (solo iconos). La primera vez o sin preferencia guardada se usa comprimido.
2. Tooltips: solo visibles cuando el rail está comprimido; no duplicar con `title` nativo si ya hay tooltip custom.
3. Usuario en rail: solo icono/avatar (sin texto del nombre del issuer en el rail). El dropdown es el mismo que ya existe (Mi plan, FIEL, Cerrar sesión, etc.).
4. Accesibilidad: `aria-expanded` en el botón expandir y en el trigger de usuario; `aria-label` en botones de icono; `focus-visible` visible.

---

## Criterios de aceptación

- [ ] Rail se ve comprimido por defecto (solo iconos, ~56px).
- [ ] Al pasar el cursor sobre un icono (comprimido), aparece un tooltip con el nombre de la página a la derecha del icono.
- [ ] Arriba del rail hay un botón (chevron) que expande el rail; al expandir se ven icono + texto de cada ítem; al pulsar de nuevo se colapsa.
- [ ] La preferencia expandido/comprimido se persiste en `localStorage` y se restaura al recargar.
- [ ] Al final del rail hay un control de usuario (solo avatar); al hacer clic se abre el dropdown de usuario (Mi plan, etc.).
- [ ] Con shell v2, el trigger de usuario de la topbar no se muestra (solo el del rail).
- [ ] El dropdown de usuario se posiciona correctamente cuando se abre desde el rail (visible y usable).

---

## Cómo probarlo manualmente

1. Con `PORTAL_SHELL_V2=1`, abrir el portal y comprobar que el rail está comprimido (solo iconos).
2. Pasar el ratón sobre cada icono y verificar que aparece el tooltip con el nombre.
3. Clic en el chevron superior: el rail se ensancha y muestra textos; clic de nuevo y se comprime. Recargar y comprobar que el estado se mantiene.
4. Ir al final del rail, clic en el avatar: debe abrirse el menú de usuario (Mi plan, Cerrar sesión, etc.) y no debe haber otro trigger de usuario en la barra superior.
5. Comprobar con teclado (Tab, Enter) y que el foco sea visible.

---

## Referencias

- Capturas de referencia Mindtrip (usuario).
- Job 4/5: navegación rail + drawer + dropdown.
