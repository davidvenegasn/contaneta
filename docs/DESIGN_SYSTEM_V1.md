# Design System v1 — Tokens y componentes

Fuente única de verdad: **portal_tokens.css** (tokens) y **components.css** (componentes UI). Las clases legacy (`.btn`, `.input`, `.card`, `.table`) se mantienen y comparten estilos con las nuevas `.ui-*` para no romper HTML existente.

---

## 1. Tokens (portal_tokens.css)

### Tipografía
| Token | Valor | Uso |
|-------|--------|-----|
| `--font-family` | Plus Jakarta Sans, system-ui… | Global |
| `--text-2xs` … `--text-3xl` | 0.6875rem … 1.75rem | Base 16px (`--text-base: 1rem`) |
| `--fw-normal` … `--fw-bold` | 400 … 700 | Pesos |
| `--leading-tight` … `--leading-relaxed` | 1.25 … 1.5 | Line-height |

### Colores
| Token | Uso |
|-------|-----|
| `--bg`, `--bg-subtle`, `--surface`, `--surface-hover` | Fondos |
| `--text`, `--text-muted`, `--text-inverse` | Texto |
| `--border`, `--border-strong` | Bordes |
| `--primary`, `--primary-hover`, `--accent`, `--accent-hover`, `--accent-soft`, `--accent-border` | Primario / accent |
| `--success`, `--success-bg`, `--success-border` | Estado éxito |
| `--warn`, `--warning`, `--warn-bg`, `--warn-border` | Advertencia |
| `--danger`, `--danger-bg`, `--danger-border` | Error |
| `--neutral`, `--neutral-bg`, `--neutral-border` | Neutro |
| `--muted`, `--focus` | Alias / focus |

### Spacing (escala 4px)
| Token | Valor |
|-------|--------|
| `--space-0` … `--space-12` | 0, 4px, 8px, 12px, 16px, 20px, 24px, 32px, 40px, 48px |

### Radius
| Token | Valor |
|-------|--------|
| `--radius-xs` … `--radius-full` | 6px, 12px, 14px, 18px, 9999px |

### Sombras
| Token | Uso |
|-------|-----|
| `--shadow-1`, `--shadow-2`, `--shadow-3` | Elevación |
| `--shadow-sm`, `--shadow-md` | Alias |
| `--shadow-focus` | Anillo de foco |

### Componentes (alturas)
| Token | Valor |
|-------|--------|
| `--input-height` | 44px |
| `--btn-height`, `--btn-height-sm`, `--btn-height-lg` | 44px, 36px, 48px |

---

## 2. Componentes UI (components.css)

### Botones
| Clase | Descripción |
|-------|-------------|
| `.ui-btn` | Base (altura 44px, tokens) |
| `.ui-btn--primary` | Primario (accent) |
| `.ui-btn--secondary` | Secundario (surface + borde) |
| `.ui-btn--ghost` | Fantasma (transparente) |
| `.ui-btn--danger` | Peligro |
| `.ui-btn--sm`, `.ui-btn--lg` | Tamaños |
| Estados | `:hover`, `:active`, `:disabled`, `:focus-visible` |

**Compat:** `.btn`, `.btn-primary`, `.btn--primary`, etc. comparten reglas con `.ui-btn` y variantes.

### Inputs
| Clase | Descripción |
|-------|-------------|
| `.ui-input` | Input de texto (altura 44px, tokens) |
| `.ui-select` | Select |
| `.ui-textarea` | Textarea |
| `.ui-input--sm` | Compacto (36px) |
| Estados | `:hover`, `:focus`, `:disabled`, `:invalid` / `.ui-input--invalid` |

**Compat:** `.input`, `.select`, `.textarea` comparten estilos con `.ui-input`, `.ui-select`, `.ui-textarea`.

### Cards
| Clase | Descripción |
|-------|-------------|
| `.ui-card` | Contenedor (surface, borde, sombra, radius) |
| `.ui-card__header` | Cabecera (padding, margin-bottom) |
| `.ui-card__title` | Título de card |
| `.ui-card__body` | Cuerpo (padding) |
| `.ui-card__footer` | Pie (borde superior, surface-hover) |

**Compat:** `.card`, `.card__header`, `.card__body`, `.card__footer` idénticos a `.ui-card` y bloques BEM.

### Tablas
| Clase | Descripción |
|-------|-------------|
| `.ui-table-wrap` | Contenedor (overflow-x, borde, radius) |
| `.ui-table` | Tabla (celdas, th con surface-hover, tokens) |
| `.ui-table-wrap--sticky` | Thead sticky (opcional) |
| `.ui-table--zebra` | Filas pares con surface-hover |

**Compat:** `.table-wrap`, `.table`, `.table--sticky`, `.table--zebra` comparten estilos con `.ui-table*`.

---

## 3. Usos reemplazados en templates (validación)

Se añadieron clases `.ui-*` **junto a las existentes** (sin quitar nada) para validar consistencia y evitar regresiones:

| Template | Cambios |
|----------|---------|
| **portal_clients.html** | `.card` → `.card ui-card`; `.card-header` → `… ui-card__header`; input búsqueda `… ui-input`; botones Nuevo / Crear primer cliente `… ui-btn ui-btn--primary`; tabla `… ui-table ui-table--zebra`. |
| **portal_products.html** | `.card` → `.card ui-card`; header `… ui-card__header`; input búsqueda `… ui-input`; botón Agregar `… ui-btn ui-btn--primary`; tabla `… ui-table`. |
| **portal_quotations.html** | `.card` → `.card ui-card`; header `… ui-card__header`; botón Nueva cotización `… ui-btn ui-btn--primary`; tabla `… ui-table`. |
| **portal_issued.html** | Card lista facturas `… ui-card`; `card__header` `… ui-card__header`; `card__body` `… ui-card__body`; `table-wrap` `… ui-table-wrap`; tabla `… ui-table ui-table--zebra`; botones empty state `… ui-btn ui-btn--primary` / `ui-btn--secondary`. |
| **portal_received.html** | Card `… ui-card`; header `… ui-card__header`; body `… ui-card__body`; table-wrap `… ui-table-wrap`; tabla `… ui-table ui-table--zebra`. |

En total: **más de 10 usos** (cards, headers, inputs, botones, tablas) en Clientes, Productos, Cotizaciones, Emitidas y Recibidas.

---

## 4. Sin regresiones

- No se eliminó ninguna clase existente; solo se añadieron `.ui-*` en los mismos nodos.
- Los estilos de `.ui-*` y los legacy están definidos con los mismos tokens y reglas en **components.css**, por lo que el aspecto en dashboard, emitidas y recibidas se mantiene igual.
- Sticky thead: seguir usando `.table-wrap.table--sticky` o `.ui-table-wrap--sticky` donde se desee.

---

*Design System v1. Próximos pasos: migrar más vistas a solo `.ui-*` cuando se quiera deprecar nombres legacy.*
