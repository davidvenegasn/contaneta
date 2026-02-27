# Orden recomendado de implementación (Spec-Driven)

Este documento define el orden sugerido para implementar las specs derivadas de la auditoría (AUDIT_README.md). El criterio es: **primero estabilidad y seguridad**, luego **funcionamiento y UX**, y al final **mantenibilidad y mejoras visuales**.

---

## Resumen de specs

| Orden | Spec | Archivo | Prioridad |
|-------|------|---------|-----------|
| 1 | Errores 500 y excepciones portal | 01_errores_500_excepciones_portal.md | Alta |
| 2 | Timeouts en fetch y feedback carga/error | 02_timeouts_fetch_feedback_carga.md | Alta |
| 3 | Sesión expirada (401) unificada | 03_sesion_expirada_401_unificada.md | Media |
| 4 | Empty states / errores / éxito consistentes | 04_empty_states_errores_exito.md | Media |
| 5 | Validación de config en prod | 09_validacion_config_prod.md | Media |
| 6 | Paginación y límites en listados | 08_paginacion_limites_listados.md | Media |
| 7 | Mensaje sync SAT y documentación | 07_sync_sat_mensaje_documentacion.md | Baja |
| 8 | Limpieza estilos inline y mejoras visuales | 05_estilos_inline_mejoras_visuales.md | Baja |
| 9 | Accesibilidad modales/drawers | 06_accesibilidad_modales_drawers.md | Baja |

---

## Orden recomendado (con dependencias)

### Fase 1 — Estabilidad (hacer primero)

1. **SPEC-01 — Errores 500 y manejo de excepciones portal**  
   No tiene dependencias. Reduce riesgo de confundir 400 con 500 y mejora logs. Tocar solo `routers/portal.py` y revisar `app.py`.

2. **SPEC-02 — Timeouts en fetch y feedback de carga/error**  
   Depende de que existan `portalFetchWithTimeout` y `portalFetchJSON` (ya existen en ui.js). Asegura que todas las pantallas usen el helper y muestren load-error con Reintentar. Base para una buena UX de errores.

### Fase 2 — Funcionamiento y UX de errores

3. **SPEC-03 — Sesión expirada (401) unificada**  
   Aprovecha el mismo helper de fetch; unifica el comportamiento ante 401 (modal + cierre overlays). Conviene después de SPEC-02 para que todos los fetch pasen por el helper.

4. **SPEC-04 — Empty states / errores / éxito consistentes**  
   Usa los mismos bloques (load-error, empty) que SPEC-02; asegura que todas las listas tengan ambos y la lógica correcta (error → load-error, 200 vacío → empty). Mejor después de SPEC-02 y opcionalmente SPEC-03.

### Fase 3 — Configuración y operación

5. **SPEC-09 — Validación de config en prod**  
   Independiente de las anteriores. Refuerza arranque en producción (SESSION_SECRET ya obligatorio; SITE_URL opcional) y documentación (.env.example, LAUNCH_CHECKLIST). Rápido de implementar.

### Fase 4 — Performance y documentación

6. **SPEC-08 — Paginación y límites en listados**  
   Backend (límite máximo, limit/offset) y frontend (controles de página). Puede hacerse en paralelo con specs de menor prioridad si el equipo es pequeño.

7. **SPEC-07 — Mensaje sync SAT y documentación**  
   Solo UI (mensaje “puede tardar”) y actualización de OPS_RUNBOOK y LAUNCH_CHECKLIST. Bajo impacto en código; alto valor para operación.

### Fase 5 — Mantenibilidad y accesibilidad

8. **SPEC-05 — Limpieza estilos inline y mejoras visuales**  
   Refactor de templates y CSS. No bloquea otras funcionalidades. Puede hacerse por pantallas (primero portal_products, portal_home).

9. **SPEC-06 — Accesibilidad modales/drawers**  
   Focus trap, Escape, aria-live, aria-label. Mejora accesibilidad sin cambiar flujos. Puede implementarse después de tener estables los modales (SPEC-02/03/04).

---

## Diagrama de dependencias (resumen)

```
SPEC-01 (errores 500)     → sin deps
SPEC-02 (timeouts/fetch)  → sin deps (usa ui.js existente)
SPEC-03 (401)             → recomienda SPEC-02 hecha
SPEC-04 (empty/error)     → recomienda SPEC-02 hecha
SPEC-09 (config prod)     → sin deps
SPEC-08 (paginación)      → sin deps
SPEC-07 (sync SAT doc)    → sin deps
SPEC-05 (estilos)         → sin deps
SPEC-06 (accesibilidad)   → sin deps (mejor con 02/03/04 estables)
```

---

## Sugerencia por sprints

- **Sprint 1:** SPEC-01, SPEC-02 (estabilidad y timeouts).
- **Sprint 2:** SPEC-03, SPEC-04 (401 y empty/error consistentes).
- **Sprint 3:** SPEC-09, SPEC-07 (config prod y documentación sync).
- **Sprint 4:** SPEC-08 (paginación; puede partirse en backend y frontend).
- **Sprint 5:** SPEC-05, SPEC-06 (estilos y accesibilidad).

---

## Notas

- La **plantilla** para nuevas specs está en `specs/_PLANTILLA_SPEC.md`.
- Las **migraciones 019 duplicadas** (AUDIT_README) no tienen spec en este set; se recomienda resolver en paralelo o antes de desplegar (renombrar una a 020 o fusionar).
- **Timeouts en subprocess** (admin backup/restore, sat_worker) están en la auditoría pero no en esta lista de specs; pueden añadirse como SPEC-10 si se desea.
- Tras implementar SPEC-02 y SPEC-04, ejecutar `scripts/audit_coverage.py` para verificar que no queden fetch sin timeout ni load-error sin usar.
