# Resumen UI/UX — Portal premium y corrección de bugs

## Archivos modificados

| Archivo | Cambios |
|---------|---------|
| `static/css/form.css` | Conceptos: grilla estable, gaps 14px, tamaños unificados (44px), responsive 1024/768/520px, focus ring, hover/active con `prefers-reduced-motion`, spacing vertical (labels 8px, card 20px, .items .item margin-bottom 14px), `.prodservBtn` 44px |
| `static/css/portal_tokens.css` | `--text-base` 16px, escalas `--text-md` a `--text-2xl` ajustadas para jerarquía |
| `static/css/portal.css` | Focus ring global: `outline 2px solid var(--accent)` en `:focus-visible` |
| `templates/form/_section_conceptos.html` | *(ningún cambio en esta sesión; cambios previos fueron namespace form-modal)* |
| `templates/base_portal.html` | *(cambios previos: mover `.form-modal` al body)* |

*(Tarea 1 ya aplicada en sesión anterior: `form.css`, `_section_conceptos.html`, `base_portal.html`, `portal.css` — namespace `.form-modal` BEM.)*

---

## Antes / Después por bug o tarea

### 1. Modales (Tarea 1 — ya hecha)
- **Antes:** `.modal` en `form.css` colisionaba con `.modal` en `portal.css`.
- **Después:** Modal de formulario (ProdServ) usa `.form-modal` y BEM (`.form-modal__backdrop`, `.form-modal__panel`, etc.). Portal sigue con `.modal` para clientes/productos/cotizaciones. Un solo sistema de modal sin colisiones.

### 2. Conceptos: grilla y encimado
- **Antes:** Gaps 12px, breakpoints 1200/980/760/520; inputs y botón ProdServ con alturas distintas (40px vs 44px); riesgo de encimar en tablet/móvil.
- **Después:** Gaps unificados a 14px en cabecera y filas; breakpoints 1200 → 1024 → 768 → 520 con mismo gap; inputs, selects, `.price-wrap input`, `.prodserv-input input` y `.prodservBtn` a **44px** de altura, mismo `border-radius: 12px` y padding; `.items` con `overflow-x: auto` para scroll horizontal si hace falta; en 520px una columna y botón quitar centrado.

### 3. Tipografía
- **Antes:** `--text-base: 0.875rem` (14px).
- **Después:** `--text-base: 1rem` (16px) en `portal_tokens.css` y en `:root` de `form.css`; `--text-md` a `--text-2xl` escalados para mantener jerarquía.

### 4. Focus ring y accesibilidad
- **Antes:** Focus en form con `outline: none` y solo borde; en portal outline neutro `rgba(0,0,0,.25)`; transforms en focus/hover sin `prefers-reduced-motion`.
- **Después:** Focus consistente: inputs/selects/textarea en form con `box-shadow: 0 0 0 3px var(--focus)`; botones y `.btn-secondary` con `:focus-visible` y mismo anillo; portal con `outline: 2px solid var(--accent)` en `:focus-visible`. Animaciones/transform (focus, hover, active) envueltas en `@media (prefers-reduced-motion: no-preference)` en form (inputs, cards, botones, `.item-row-top`).

### 5. Spacing vertical
- **Antes:** Labels `margin-bottom: 6px`, cards `padding: 16px`, filas de conceptos sin margen entre sí.
- **Después:** Labels `margin-bottom: 8px`; cards `padding: 20px`; `.items .item` con `margin-bottom: 14px` (último hijo 0).

---

## Verificación por breakpoints

Recomendado revisar en:

- **1440px:** Conceptos en 7 columnas (`--concept-cols`), cabecera visible, sin scroll horizontal si hay espacio; tipografía y focus ring correctos.
- **1024px:** Conceptos en 3 columnas con labels por campo; sin encimar; botón ProdServ 44px alineado.
- **390px:** Conceptos en 1 columna (stacked); cada fila como “tarjeta”; scroll horizontal suave en `.items` si algún contenido lo requiere; botón quitar centrado.

*(No se ha cambiado lógica de backend; solo HTML/CSS/JS de UI donde se tocó; estética mint/verde mantenida.)*
