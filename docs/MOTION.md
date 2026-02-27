# P48 Motion — Estándar Phantom

Objetivo: animaciones y transiciones **consistentes** en todo el portal (sensación uniforme).

## Duraciones estándar (tokens)

Definidos en `static/css/portal_tokens.css`:

| Token | Valor | Uso |
|-------|--------|-----|
| `--motion-micro` | **150ms** | Hovers, focus, micro-interacciones (botones, links, celdas). |
| `--motion-modal` | **200ms** | Modales, drawers, overlays, toasts, menús desplegables. |
| `--motion-page` | **180ms** | Entrada/salida de página, barra de progreso, transiciones de ruta. |

Easing: `--ease-out`, `--ease-in-out` (también en tokens).

## Uso en CSS

- Preferir siempre los tokens: `transition: opacity var(--motion-modal, 200ms) ease;`
- No usar valores sueltos (ej. `140ms`, `.25s`) salvo delays de stagger (ej. `animation-delay: 30ms`).

## Reduced motion

- **Global:** En `portal.css`, `@media (prefers-reduced-motion: reduce)` aplica a `*`: `animation-duration` y `transition-duration` → `0.01ms`, `animation-iteration-count: 1`, `scroll-behavior: auto`.
- **Local:** Varios bloques (fade-in, skeleton, page-enter, loading bar, menús) tienen `@media (prefers-reduced-motion: no-preference)` para animar solo cuando el usuario no ha pedido reducir movimiento, y `@media (prefers-reduced-motion: reduce)` para desactivar o simplificar.

Con esto las animaciones se sienten **uniformes** y se respeta la preferencia de accesibilidad.
