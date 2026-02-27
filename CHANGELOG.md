# Changelog

## [Unreleased]

### Added
- **P47 Keyboard shortcuts:** `/` enfoca el buscador en listados (emitidas, recibidas, clientes, productos, proveedores). `g h` = Inicio, `g i` = Emitidas, `g r` = Recibidas. `Esc` cierra el modal/drawer visible (PDF, confirmación, sesión expirada, drawer CFDI, drawer proveedores, modal cotizaciones, menú usuario). Se ignoran atajos cuando el foco está en input/textarea/select para no romper la escritura.

- **P46 Autosave local (cotizaciones):** Borrador del modal de nueva cotización se guarda en localStorage cada 500 ms (cliente, conceptos, notas). Al abrir el modal se restaura si existe borrador, con toast "Borrador restaurado". Botón "Descartar borrador" limpia el borrador local y el formulario. Tras guardar o enviar, se borra el borrador local. Sin tocar DB.

- **P45 Session expired UX:** Ante 401 en uiFetchJSON se muestra un modal "Sesión expirada" con botón "Iniciar sesión" (enlace a /login). Se cierran automáticamente los overlays/drawers abiertos (CFDI, proveedores, PDF) para no dejar la UI rota. No se muestra el mensaje crudo "No autorizado".

- **P44 Impersonation UX segura:** Banner de impersonación con color distintivo (violeta/morado) y etiqueta "Modo soporte", sticky en la parte superior para que no se confunda con el usuario normal. Botón fijo "Salir de impersonación" en la esquina inferior derecha siempre visible. audit_log ya registraba `impersonate_start` e `impersonate_stop` (sin cambios).

- **P43 FIEL UI premium:** Página Conectar SAT con dropzones estilizadas (arrastrar y soltar, nombre + tamaño del archivo), estados claros (No configurado, Validando…, Válida ✓, Error con mensaje legible) y look fintech trust (cards con sombra, bordes y jerarquía visual).

- **P42 Microcopy polish (COPY_PORTAL.md):** Textos estándar para errores de carga ("No pudimos cargar esto ahora." + Reintentar), empty states, botones y FIEL. En FIEL (Conectar SAT) se añade una línea explicando qué es la FIEL y para qué la usamos. Ver COPY_PORTAL.md.

- **P41 Detalle CFDI como drawer:** En emitidas y recibidas, al hacer clic en una fila o en el enlace "Detalle" se abre un drawer lateral con UUID, receptor/emisor, concepto, totales, estatus y botones PDF/XML/Copiar UUID y "Ver página completa". Cierre con ESC, clic en overlay y scroll interno en el panel. Sin recargar la página.

- **Demo móvil estable (backlog must/should):** A2 SESSION_SECRET obligatorio en prod y documentado; A4 FIEL validación post-upload con estado en UI y "Validar de nuevo"; Home Factura rápida con modales Añadir cliente/producto que guardan, refrescan y seleccionan; empty states en listas (200+[] → empty state, error solo con status ≥400); un solo mensaje de error (sin toast+bloque); drawer proveedores con ESC, focus trap, overlay y en 390px full screen y botones tocables; table-wrap con scroll interno en 390px. Ver DEMO_10MIN_NOTES.md y QA_MOBILE_SMOKE.md.

### Fixed

- **DEV_MODE default por entorno:** En entornos que no sean explícitamente desarrollo (`ENV=dev`), el default de `DEV_MODE` es ahora **0**, evitando caer al acceso demo por defecto en producción. Con `ENV=dev` el default sigue siendo `1`. Solo se usa demo cuando `DEV_MODE=1` está explícitamente definido. Ver `config.py` y DECISIONS.md.

- **Fallback de sesión en portal:** Sin cookie válida, las rutas HTML del portal redirigen a `/login` (302) y las API devuelven 401 JSON. El fallback al issuer demo solo ocurre si `ALLOW_DEMO_PORTAL=1` (y `DEV_MODE=1`). Default `ALLOW_DEMO_PORTAL=0`: ya no hay "brincos" al demo al navegar. Ver `routers/deps.py` y DECISIONS.md.
