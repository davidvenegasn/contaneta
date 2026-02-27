# Estilo de iconos — ContaNeta

Consistencia visual: un solo criterio para todos los iconos del producto.

## Estándar

- **Tipo:** SVG inline (sin librerías externas).
- **ViewBox:** `0 0 24 24`.
- **Trazo:** `stroke-width: 1.75`, `stroke-linecap: round`, `stroke-linejoin: round`, `fill: none`, `stroke: currentColor`.
- **Tamaño:** Controlado por CSS con la clase `.icon` o variables:
  - `--icon-size: 1.25em` (por defecto)
  - `--icon-size-sm: 1rem`
  - `--icon-size-lg: 1.5rem`
- **Tokens:** En `static/css/portal_tokens.css`: `--icon-stroke: 1.75`, `--icon-size`, `--icon-size-sm`, `--icon-size-lg`.

## Uso en plantillas

- Añadir clase `class="icon"` al `<svg>` para que herede tamaño y trazo desde CSS.
- Si el SVG lleva `stroke-width` en el HTML, usar `1.75` para alinearlo al estándar.
- Iconos decorativos grandes (p. ej. overlay de éxito) pueden usar `stroke-width: 2.5` para mayor visibilidad.

## Uso en CSS

- Los elementos `.icon` y `.portal svg.icon` reciben `stroke-width: var(--icon-stroke, 1.75)` desde `portal.css`.
- Para variar el grosor en un contexto concreto, sobrescribir con `--icon-stroke` en ese contenedor.

## Excepciones

- **OAuth (Google/Facebook):** iconos de marca con `fill` de color; no se cambian.
- **Chevron/accordion en data URL:** usar `stroke-width='1.75'` en el SVG codificado.
