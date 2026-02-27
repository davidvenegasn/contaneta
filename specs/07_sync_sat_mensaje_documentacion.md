# Spec: Mensaje de sync SAT y documentación

**ID:** `SPEC-07`  
**Origen:** AUDIT_README.md — Funcionamiento, Job 10  
**Prioridad:** Baja

---

## Objetivo

Informar al usuario en la UI que la sincronización SAT puede tardar unos minutos y que, si no ve datos, puede reintentar más tarde o revisar la configuración. Además, documentar en OPS_RUNBOOK (y opcionalmente en LAUNCH_CHECKLIST) los pasos para configurar el cron o sat_worker y qué esperar al pulsar "Sync".

---

## Alcance

- UI del portal: en la pantalla o barra donde está el botón "Sync SAT" (o equivalente), añadir un texto corto visible que diga que la sincronización puede tardar unos minutos y que si no aparecen datos puede reintentar o revisar la configuración SAT. Puede ser un hint bajo el botón, un tooltip, o una línea en la barra de sync (portal_list_sync_bar.html si existe).
- Documentación: actualizar OPS_RUNBOOK.md con (1) requisito de PHP para FIEL y scripts SAT, (2) cómo configurar el cron o `scripts/sat_worker.py` para procesar jobs de sync, (3) qué hace el botón "Sync" (encolar job) y que el procesamiento es asíncrono.
- Opcional: en LAUNCH_CHECKLIST.md añadir ítem "Configurar cron SAT / sat_worker" y referencia a OPS_RUNBOOK.

---

## Fuera de alcance

- Cambiar la lógica de encolado o procesamiento del sync (backend).
- Añadir polling en la UI para mostrar "Sincronizando…" en tiempo real.
- Documentación de otros módulos (solo SAT y sync).
- Resolver migraciones 019 u otras tareas de BD.

---

## Archivos a tocar

| Archivo / directorio | Cambio previsto |
|----------------------|-----------------|
| `templates/portal_list_sync_bar.html` | Añadir una línea de texto (o bloque) con el mensaje: "La sincronización puede tardar unos minutos. Si no ves datos, vuelve a intentar más tarde o revisa tu configuración SAT." (o redacción acordada). |
| O el template que contenga el botón Sync SAT (ej. base_portal, portal_home, portal_issued, portal_received) | Si el botón está en otro lugar, añadir el mensaje cerca del botón o en la sección de configuración SAT. |
| `OPS_RUNBOOK.md` | Añadir sección o párrafos: requisito de PHP para FIEL y descarga SAT; cómo configurar cron o sat_worker.py; qué hace "Sync" (encola job) y que el procesamiento es asíncrono; qué revisar si no llegan datos (cron activo, logs, configuración SAT). |
| `LAUNCH_CHECKLIST.md` | Opcional: ítem "Configurar cron SAT / sat_worker" con enlace o referencia a OPS_RUNBOOK. |
| `.env.example` u otra doc de configuración | Opcional: mencionar que para sync SAT se necesita cron o worker (ver OPS_RUNBOOK). |

---

## Reglas

1. El mensaje en la UI debe ser visible sin tener que abrir un modal; puede ser texto secundario (muted) bajo el botón o en la barra de sync.
2. No sustituir el mensaje de éxito "Sincronización iniciada" por el nuevo texto; complementar: el usuario sigue viendo que la acción se aceptó y además sabe que puede tardar.
3. La documentación en OPS_RUNBOOK debe permitir a un operador configurar el cron o sat_worker desde cero (ruta del script, frecuencia, variables de entorno si aplican, cómo verificar que está corriendo).
4. Mencionar explícitamente que PHP es requisito para validación FIEL y para los scripts de descarga SAT (si se invocan vía subprocess).

---

## Criterios de aceptación

- [ ] En la UI del portal aparece un texto que informa que la sincronización puede tardar unos minutos y que si no hay datos se puede reintentar o revisar la configuración.
- [ ] OPS_RUNBOOK.md incluye: requisito de PHP para FIEL/SAT, configuración de cron o sat_worker, descripción del flujo "Sync" (encolar job, procesamiento asíncrono), y pasos para diagnosticar cuando no llegan datos.
- [ ] Opcional: LAUNCH_CHECKLIST.md incluye ítem de configuración de cron SAT con referencia a OPS_RUNBOOK.
- [ ] El mensaje en la UI no es intrusivo (no bloquea ni sustituye el flujo actual del botón Sync).

---

## Cómo probarlo manualmente

1. **UI:** Ir a una pantalla donde esté el botón Sync SAT (emitidas, recibidas o barra de sync). Verificar que el nuevo texto sea visible (bajo el botón o en la barra).
2. **Flujo:** Pulsar Sync; debe seguir mostrándose "Sincronización iniciada" o equivalente, y el mensaje de "puede tardar" debe estar visible para quien quiera leerlo.
3. **Documentación:** Seguir los pasos de OPS_RUNBOOK para configurar el cron o sat_worker en un entorno de prueba y verificar que la redacción sea clara. Revisar que LAUNCH_CHECKLIST (si se actualizó) enlace correctamente.

---

## Referencias

- AUDIT_README.md — Sección 2.2 (Sync SAT), Job 10.
- OPS_RUNBOOK.md — Operación y cron.
- LAUNCH_CHECKLIST.md — Puesta en marcha.
- scripts/sat_worker.py — Procesamiento de jobs SAT.
