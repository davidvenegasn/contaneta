# Instrucciones para Claude Code — Instalar Dashboard v2

**IMPORTANTE:** Este handoff es **100% aditivo**. No sustituye ni elimina nada
del proyecto actual. Crea 3 archivos nuevos y modifica 2 existentes con
inserciones mínimas. El usuario puede revertir todo con un git stash.

## Objetivo

Añadir al dashboard (`templates/portal_home.html`) un bloque nuevo arriba,
estilo Revolut:
- Card grande con "Tus ingresos del mes: $XX,XXX.XX" y delta vs mes anterior.
- 3 cuadros chicos (Gastos / IVA cobrado / IVA pagado) con colores distintos.
- Botón flotante para toggle dark/light.

El bloque existente de KPIs (`.ui-kpi-grid.dashboard-metrics`) y la gráfica de
6 meses del proyecto **NO se tocan**, siguen exactamente igual.

## Paso 1 — Copia tal cual estos 3 archivos

Copia estos archivos del paquete `handoff_pack/` a las rutas indicadas
**sin modificar nada de su contenido**:

| Origen | Destino |
|---|---|
| `handoff_pack/static/css/portal_dashboard_v2.css`       | `static/css/portal_dashboard_v2.css` |
| `handoff_pack/static/js/portal_dashboard_v2.js`         | `static/js/portal_dashboard_v2.js` |
| `handoff_pack/templates/partials/_dashboard_balance_v2.html` | `templates/partials/_dashboard_balance_v2.html` |

Si la carpeta `templates/partials/` no existe, créala.

## Paso 2 — Modifica `templates/base_portal.html`

**Ubicación:** después de la línea donde se carga `portal.css` (línea ~57
según el reporte del usuario), al final del grupo de `<link rel="stylesheet">`.

**Añade estas 2 líneas** (nada más):

```html
<link rel="stylesheet" href="/static/css/portal_dashboard_v2.css">
<script defer src="/static/js/portal_dashboard_v2.js"></script>
```

**Ejemplo exacto del contexto esperado** (las líneas existentes NO cambian):

```html
<link rel="stylesheet" href="/static/css/portal_sidebar_unified.css">
<link rel="stylesheet" href="/static/css/portal.css">
<link rel="stylesheet" href="/static/css/portal_dashboard_v2.css">   <!-- NUEVO -->
<script defer src="/static/js/portal_dashboard_v2.js"></script>       <!-- NUEVO -->
<link rel="stylesheet" href="/static/css/command-palette.css">
```

## Paso 3 — Modifica `templates/portal_home.html`

**Ubicación:** justo ANTES del bloque `<div class="ui-kpi-grid dashboard-metrics">`
(línea ~135 según el reporte del usuario).

**Añade esta línea** (nada más):

```jinja
{% include 'partials/_dashboard_balance_v2.html' %}
```

**Ejemplo exacto del contexto esperado** (las líneas existentes NO cambian):

```jinja
{# ... código previo del template ... #}

{% include 'partials/_dashboard_balance_v2.html' %}   {# NUEVO — balance card v2 #}

<div class="ui-kpi-grid dashboard-metrics">
  {% set trends = kpi_trends|default({}) %}
  <a href="/portal/facturas?tab=issued" class="ui-kpi-card card metric-card metric-card--link" ...>
    ...
```

## Reglas importantes

1. **NO elimines** el bloque `.ui-kpi-grid.dashboard-metrics` ni ninguno de
   sus 4 KPI cards. El usuario quiere que el balance card v2 aparezca
   **arriba** del grid existente.
2. **NO modifiques** la gráfica de 6 meses ni ningún otro bloque del home.
3. **NO añadas** imports nuevos de fuentes (Inter ya está en el base).
4. **NO toques** `portal_tokens.css`, `portal_sidebar_unified.css` ni ningún
   CSS existente.
5. Si alguna línea de las que te pido insertar YA existe en el archivo, no
   la dupliques — solo reporta "ya existe".

## Validación (paso 4, manual — informa al usuario)

Tras aplicar los 3 pasos, el usuario debe:
1. Reiniciar el servidor FastAPI (Ctrl+C y volver a `uvicorn main:app --reload`).
2. Refrescar el navegador con Ctrl+Shift+R (hard refresh, sin caché).
3. Entrar al portal: debería ver la nueva card arriba.
4. Probar el botón circular abajo-derecha: alterna light/dark.

Si el dashboard se ve vacío o roto, revertir los cambios con `git stash` y
reportarlo al usuario.
