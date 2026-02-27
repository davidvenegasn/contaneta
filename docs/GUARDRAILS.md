# Guardrails — archivos sagrados y reglas de edición

Este documento define qué no se debe tocar y cómo editar el proyecto sin romper el portal. Léelo antes de refactors o cambios estructurales.

---

## 1. Carpeta `_snapshot_before_mindtrip/`

- **Estado:** No se usa en runtime. Es una copia de respaldo de templates/ y static/ en un punto anterior.
- **Regla:** **Nunca editar** esta carpeta. Causa confusión si Cursor o herramientas la modifican.
- **Acción tomada:** Añadida a `.gitignore` para que no se trackee. Si existe en tu copia, no la borres a ciegas; simplemente no la incluyas en commits.
- Si en el futuro se quiere archivar por completo: mover a `backup/_snapshot_before_mindtrip_ARCHIVED/` y dejar un README allí explicando el origen.

---

## 2. `templates/base_portal.html`

- **Crítico:** Todas las páginas del portal extienden esta base y usan `{% block content %}`.
- **Reglas:**
  - No eliminar ni renombrar `{% block content %}` ni su `{% endblock %}`.
  - No introducir nuevos blocks requeridos sin actualizar todas las páginas que extienden la base.
  - Al extraer componentes, usar `{% include %}` sin cambiar variables que esperan las páginas (`issuer`, `csrf_token`, `active_page`, `title`, etc.).
- **Validación:** `scripts/guardrails_check.sh` comprueba que existan `{% block content %}` y `{% endblock %}`.

---

## 3. Autenticación e identidad

- **`routers/deps.py` → `get_portal_issuer(request)`:** Resuelve la identidad del emisor (cookie o token). No cambiar la lógica de identidad; el `issuer_id` **siempre** debe venir de sesión, nunca de query/body.
- **Multi-tenant:** Todas las consultas y descargas filtran por `issuer_id` obtenido de `get_portal_issuer`. No añadir rutas que acepten `issuer_id` desde el cliente.

---

## 4. Base de datos y SQL

- **`database.py`:** Usar `db()`, `db_rows()`, `db_execute()`. SQL **siempre parametrizado** (? o :name); nombres de tabla/columna nunca desde entrada de usuario.
- No duplicar lógica de migraciones: el flujo oficial es `migrations/*.sql` + `migrations_runner.py`. No ejecutar scripts `db_migrate_*.py` en raíz sin coordinación.

---

## 5. Lógica contable / SAT / CFDI

- No cambiar cálculos de totales, IVA, retenciones en facturas.
- No cambiar parsing ni almacenamiento de XML CFDI ni flujos de sincronización SAT.
- No cambiar validación FIEL ni invocación de scripts PHP de `sat_sync/` sin revisar timeouts y seguridad.

---

## 6. Stack técnico (no introducir)

- **No** React, Tailwind ni ningún framework frontend.
- **No** bundlers (webpack, Vite, etc.). CSS y JS plano en `static/`.
- Cambios **incrementales** y validables: tras cada cambio relevante, ejecutar `./scripts/smoke_portal.sh` y `python -m tests.test_import`.

---

## 7. Script de verificación

- **`scripts/guardrails_check.sh`:** Falla si se modifican archivos bajo `_snapshot_before_mindtrip` o si `base_portal.html` pierde los blocks requeridos. Integrado en el flujo de smoke cuando existe.
- Ejecutar manualmente antes de commits grandes: `./scripts/guardrails_check.sh`

---

## 8. Resumen para IA / Cursor

- Leer `docs/README_FOR_AI.md` y este archivo antes de tocar código.
- No editar `_snapshot_before_mindtrip`.
- No romper `{% block content %}` en `base_portal.html`.
- No cambiar identidad en `get_portal_issuer` ni SQL de negocio.
- Validar con smoke y test_import después de cada fase.
