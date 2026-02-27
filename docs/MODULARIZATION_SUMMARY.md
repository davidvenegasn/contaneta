# Modularización y guardrails (resumen)

Resumen de lo aplicado en la rama `refactor/guardrails-modularize`: archivos sagrados, CSS por capas y componentes de templates.

---

## 1. Snapshot y guardrails

- **`_snapshot_before_mindtrip/`:** No se usa en runtime. Añadida a `.gitignore` para no trackearla ni editarla por error.
- **`docs/GUARDRAILS.md`:** Reglas de archivos sagrados (base_portal, get_portal_issuer, database, lógica SAT) y qué no tocar.
- **`scripts/guardrails_check.sh`:** Comprueba que no se modifiquen archivos bajo `_snapshot_before_mindtrip` y que `base_portal.html` conserve `{% block content %}` y `{% endblock %}`. Integrado en `scripts/smoke_portal.sh`.

---

## 2. CSS modularizado

- **`static/css/portal_shell.css`:** Layout del portal (`.portal`, `.portal-shell`, sidebar, nav, modal estructura, main).
- **`static/css/portal_components.css`:** Utilidades, headings, tablas, paginación, card invoice list.
- **`static/css/portal_pages.css`:** Placeholder para estilos por página (el resto sigue en `portal.css`).
- **`static/css/portal.css`:** Sigue siendo la **entrada única**: incluye los tres archivos con `@import` y contiene el resto de reglas (topbar, chips, user menu, dashboard, bank, resumen, responsive, etc.). No hay paso de build.
- **`docs/CSS_ARCHITECTURE.md`:** Orden de carga, convención shell / components / pages y cómo editar sin romper.

---

## 3. Componentes de templates

- **`templates/components/breadcrumbs.html`:** Breadcrumb del topbar. Incluido desde `base_portal.html`. Usa la variable `active_page` del contexto.
- Ya existían: `components/portal_rail.html`, `components/portal_drawer.html`, `empty_state.html`, `error_state.html`.
- **`docs/FRONTEND_GUIDE.md`:** Actualizado con el orden de CSS (portal.css como entrada que importa capas) y la mención a `components/breadcrumbs.html`.

---

## 4. Cómo validar

- **Guardrails:** `./scripts/guardrails_check.sh`
- **Smoke portal:** `./scripts/smoke_portal.sh` (incluye guardrails si el script existe).
- **Imports:** `python3 -m tests.test_import`

Si algo falla tras un cambio, revertir la fase afectada y corregir antes de seguir.

---

## 5. Pendiente (opcional)

- **Dividir `routers/portal.py`** por dominio (portal_home, portal_invoices, portal_bank, portal_catalogs) sin cambiar URLs ni comportamiento. Documentado como pendiente en `docs/AUDIT_REPORT.md` o en este resumen; solo hacerlo si el smoke y los tests siguen en verde y no hay imports cíclicos.
