# Patrones de UI del portal

Patrones visuales unificados para listas vacías, error de carga y toasts. Mismo look & feel en todas las pantallas; evitar estilos inline y bloques ad-hoc.

---

## 1. Empty state (lista vacía)

**Cuándo:** La petición devolvió **200** y la lista está **vacía** (no es un error).

- Clases: `empty-state empty-state--empty`
- Estructura: icono (opcional), título, descripción, zona de acciones (CTA).
- Uso en Jinja: macro `portal_empty_state(title, desc, id=none, show_icon=true, extra_class='')` en `templates/portal/_ui_components.html`. Las acciones se pasan con `{% call %}...{% endcall %}`.

**Ejemplo:**

```html
{% from 'portal/_ui_components.html' import portal_empty_state %}
{% call portal_empty_state('Aún no hay clientes', 'Descripción breve.', id='emptyState') %}
  <a href="/portal/clients/refresh" class="btn btn--primary">Actualizar ahora</a>
{% endcall %}
```

- **Empty ≠ Error:** no usar `empty-state--error` cuando solo hay 0 resultados.

---

## 2. Error de carga (load-error)

**Cuándo:** El **fetch falló** (timeout, red, 5xx) o el servidor respondió con error. No cuando la API devuelve 200 con lista vacía.

- Clases: `empty-state empty-state--error load-error`
- Estructura fija: título "No pudimos cargar esto ahora.", mensaje (id `{prefix}Msg`), botón "Reintentar" (id `{prefix}Retry`).
- Uso en Jinja: macro `portal_load_error(id_prefix, extra_class='')`. El JS usa los ids `{prefix}`, `{prefix}Msg`, `{prefix}Retry` para mostrar mensaje y enlazar el retry.

**Ejemplo:**

```html
{% from 'portal/_ui_components.html' import portal_load_error %}
{{ portal_load_error('loadErrorState') }}
```

En JS: mostrar el bloque cuando falle la petición; ocultar cuando haya carga correcta (datos o lista vacía). Para errores con mensaje dinámico, actualizar el texto de `document.getElementById(idPrefix + 'Msg')`.

- **Distinción:** 200 + `[]` → empty state. Timeout / red / 401 / 5xx → load-error.

---

## 3. Toast (éxito / error / info)

**Cuándo:** Feedback de una acción (guardado, error de validación, aviso).

- API: `window.portalToast({ type, title, message, ttl })`
- `type`: `'success'` | `'danger'` | `'warning'` | `'info'` (el portal mapea `'error'` → `'danger'`).
- No usar toasts para estados de carga de listas (usar skeletons y load-error).

**Ejemplo:**

```javascript
window.portalToast({ type: 'success', title: 'Guardado', message: 'Cliente actualizado.' });
window.portalToast({ type: 'danger', title: 'Error', message: 'Revisa los datos e intenta de nuevo.', ttl: 5000 });
```

- Contenedor: `#toastStack` en `base_portal.html`. Máximo 3 toasts visibles; se eliminan por tiempo (`ttl`).

---

## 4. Banners persistentes (éxito / aviso / error)

**Cuándo:** Avisos importantes que deben permanecer visibles hasta que el usuario cierre o cambie de página (no se ocultan solos).

- **Toasts** = feedback inmediato de una acción (se ocultan solos).
- **Banners** = mensajes que requieren atención: “Sync SAT puede tardar unos minutos”, errores de proceso que conviene no perder de vista.

- API: `window.portalBanner({ type, title, message, id?, dismissible? })`
- `type`: `'success'` | `'warning'` | `'error'`
- `id`: opcional; si se repite, se reemplaza el banner anterior con ese id (ej. un solo aviso de “sync” a la vez).
- `dismissible`: si es `true` (por defecto), se muestra botón × para cerrar.
- Quitar por id: `window.portalBannerClear('sync-warning')`

**Ejemplo:**

```javascript
window.portalBanner({ id: 'sync-warning', type: 'warning', title: 'Sync SAT', message: 'Puede tardar unos minutos. Los CFDI se descargan en segundo plano.', dismissible: true });
```

- Contenedor: `#portalBanners` en `base_portal.html`. Estilos: `.portal-banner`, `.portal-banner--success`, `.portal-banner--warning`, `.portal-banner--error` en `portal.css`.

---

## Resumen

| Caso              | Componente     | Condición              |
|-------------------|----------------|------------------------|
| Lista vacía       | empty-state    | 200 + lista vacía      |
| Fallo de petición | load-error     | timeout / red / 4xx/5xx|
| Feedback inmediato| toast          | Después de submit/click; se oculta solo |
| Aviso importante  | portal-banner  | Éxito/aviso/error que debe persistir (ej. “sync tardará”) |

Componentes reutilizables: `templates/portal/_ui_components.html`. Estilos: `static/css/portal.css` (`.empty-state`, `.empty-state--empty`, `.empty-state--error`, `.load-error`, `.toast`, `.portal-banner`).
