# Spec: Limpieza de estilos inline y mejoras visuales

**ID:** `SPEC-05`  
**Origen:** AUDIT_README.md — Mantenibilidad / UX, Job 11 (estilos)  
**Prioridad:** Baja

---

## Objetivo

Reducir estilos inline en templates del portal y unificar espaciados y jerarquía visual usando clases en `portal.css`/`components.css` y variables de `portal_tokens.css`. Mejorar coherencia visual y facilitar mantenimiento.

---

## Alcance

- Templates del portal con atributos `style="..."` (márgenes, paddings, colores, fuentes). Mover esos estilos a clases en CSS.
- Uso de utilidades y variables: `--space-*`, `--radius`, clases `.u-m*`, `.u-p*` de `portal.css`.
- Opcional: breadcrumbs en detalle CFDI y detalle cotización (Inicio › Emitidas › [UUID]). Si no hay componente de breadcrumb, enlace "Volver al listado" consistente.
- Revisión de nombres de enlaces ("Factura rápida" vs "Genera factura") para consistencia.

---

## Fuera de alcance

- Rediseño completo de la UI.
- Cambios de lógica o comportamiento.
- Accesibilidad de modales (spec 06).
- Nuevas funcionalidades.

---

## Archivos a tocar

| Archivo / directorio | Cambio previsto |
|----------------------|-----------------|
| `templates/portal_products.html` | Sustituir estilos inline por clases. |
| `templates/portal_home.html` | Igual. |
| Otros `templates/portal_*.html` con `style="..."` | Sustituir por clases. |
| `static/css/portal.css` | Añadir clases necesarias usando variables de tokens. |
| `static/css/components.css` | Ajustar clases reutilizables si aplica. |
| Templates detalle CFDI y cotización | Breadcrumb o "Volver a [listado]" consistente (opcional). |

---

## Reglas

1. No dejar estilos inline para espaciado, color o tipografía salvo valor dinámico; documentar excepciones.
2. Nuevas clases reutilizables y con variables de `portal_tokens.css`.
3. Apariencia visual actual mantenida; solo cambia implementación (inline → clase).
4. Breadcrumbs misma estructura en detalle CFDI y detalle cotización si se implementan.

---

## Criterios de aceptación

- [ ] Estilos inline reducidos al mínimo en templates revisados (portal_products, portal_home y los identificados).
- [ ] Estilos en CSS usan variables de `portal_tokens.css` donde sea posible.
- [ ] Apariencia visual se mantiene.
- [ ] Opcional: detalle CFDI y cotización con breadcrumb o "Volver a [listado]" consistente.
- [ ] Opcional: nombres de enlaces consistentes y rutas correctas.

---

## Cómo probarlo manualmente

1. Recorrer portal_products, portal_home y pantallas modificadas; verificar que se vean igual.
2. Comprobar en viewport reducido que espaciados se mantienen.
3. Si hay breadcrumb, verificar en detalle factura y cotización que "Volver" lleve al listado correcto.
4. Pulsar enlaces principales y comprobar navegación esperada.

---

## Referencias

- AUDIT_README.md — Sección 4.5, 6.3, Job 11.
- static/css/portal_tokens.css, portal.css.
