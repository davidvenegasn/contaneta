# Arquitectura CSS del portal

Capas del CSS del portal (sin build step). El orden de carga en `base_portal.html` debe respetarse para que los tokens y el layout no se pisen.

---

## Orden de carga (recomendado)

1. **form.css** — base de formularios y layout global.
2. **portal_tokens.css** — variables (colores, espaciado, tipografía). No definir reglas de componentes aquí.
3. **components.css** — componentes compartidos (botones, inputs, cards) de la librería UI.
4. **portal.css** — entrada principal del portal; puede ser un “shim” que importa las capas siguientes o contener todo.
5. **portal_shell.css** — layout del portal: `.portal`, `.portal-shell`, sidebar, nav, topbar, modal estructura, user menu.
6. **portal_components.css** — componentes específicos del portal: tablas, paginación, empty state, skeleton, toasts, badges/pills.
7. **portal_pages.css** — estilos por página: dashboard, facturas, bancos, resumen, filtros, responsive por vista.
8. **portal_ui_v2.css**, **portal_rail.css** — según necesidad (v2, rail).

---

## Convención

- **Shell:** todo lo que define la “caja” del portal (sidebar, topbar, main, modal contenedor). No colores de negocio ni contenido.
- **Components:** piezas reutilizables (cards, tables, buttons del portal, empty state, skeleton). Usan tokens.
- **Pages:** reglas que dependen de la página o de la vista (ej. `.card--invoice-list`, `.bank-*`, `.ym-card`, resumen colapsable). Responsive por sección va aquí.

---

## Cómo editar sin romper

- No eliminar reglas que sigan en uso; si se mueven a otro archivo, quitarlas del original para evitar duplicados.
- No abusar de `!important`; preferir especificidad o variables.
- Al añadir estilos nuevos, colocarlos en el archivo que corresponda (shell / components / pages) según la convención de arriba.
