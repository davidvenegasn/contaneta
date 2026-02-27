# Accesibilidad (A11Y) — ContaNeta

Objetivo: experiencia usable con teclado y lectores de pantalla, y contraste mínimo razonable.

## Focus visible

- **Solo `:focus-visible`:** el anillo de foco se muestra al navegar con teclado (Tab), no al hacer clic con ratón.
- **Token:** `--focus-ring` y `--focus-ring-offset` en `portal_tokens.css`. Uso en `portal.css` para enlaces, botones, inputs, selects, textareas y elementos con `tabindex`.
- **Sidebar (menú móvil):** el botón de abrir y el de cerrar tienen el mismo anillo de foco (accent en modo claro, blanco semitransparente en modo noche).
- **Formularios:** en `form.css` los controles usan `box-shadow` para el foco visible (compatible con el resto del diseño).

No se usa `outline: none` sin reemplazo en `:focus-visible`; en los casos que lo anulaban (p. ej. sidebar) se aplica un outline explícito.

## ARIA

### Menú móvil (sidebar)

- Botón abrir: `aria-label="Abrir menú"`, `aria-controls="sidebar"`, `aria-expanded` actualizado por JS al abrir/cerrar.
- Botón cerrar: `aria-label="Cerrar menú"`.
- Sidebar: `aria-label="Menú de navegación"`, `aria-hidden` actualizado por JS (true cuando está cerrado).

### Menú de usuario (dropdown)

- Botón: `aria-haspopup="menu"`, `aria-expanded` actualizado por JS.
- Panel: `role="menu"`, ítems con `role="menuitem"`. Uso de `hidden` para ocultar cuando está cerrado.

### Acordeón (pricing — comparar planes)

- Contenedor: `role="list"`, cada ítem `role="listitem"`.
- Botón del acordeón: `aria-expanded`, `aria-controls` apuntando al id del panel.
- Panel: `id` coincidente con `aria-controls`, `aria-labelledby` apuntando al botón, `role="region"`. Atributo `hidden` cuando está cerrado; el JS lo sincroniza con `aria-expanded`.

## Contraste (check básico)

Valores aproximados con los tokens actuales (modo claro):

| Combinación | Uso | Notas |
|-------------|-----|--------|
| `--text` (#0d1f1c) sobre `--bg` (#f0fdf9) | Texto principal | Contraste alto, cumple AA. |
| `--text-muted` (#3d524f) sobre `--bg` | Texto secundario | >4.5:1 en la mayoría de pantallas; revisar en pantallas mal calibradas. |
| `--accent` (#14b8a6) sobre blanco | Botones primarios, enlaces | Cumple AA para texto grande; para texto pequeño considerar oscurecer en futuras iteraciones. |
| Botones primarios: texto blanco sobre `--accent` | CTAs | Alto contraste. |

Recomendación: no bajar más el contraste de `--text-muted` sobre fondos claros; para modo noche ya se usa outline claro sobre fondo oscuro para el foco.

## Resumen

- Focus visible consistente en portal, formularios y pricing.
- ARIA en menú móvil, menú de usuario y acordeón de comparación de planes.
- Contraste básico documentado; sin cambios de color en esta pasada.
