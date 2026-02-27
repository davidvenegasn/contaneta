# Spec: Validación de configuración en producción (SESSION_SECRET, SITE_URL)

**ID:** `SPEC-09`  
**Origen:** AUDIT_README.md — Seguridad / Operación, Job 8  
**Prioridad:** Media

---

## Objetivo

Reforzar la validación de configuración en arranque cuando `ENV=prod`: ya se exige SESSION_SECRET; añadir comprobación opcional de SITE_URL cuando se use billing o redirecciones que dependan de ella. Documentar en .env.example y LAUNCH_CHECKLIST las variables críticas para producción.

---

## Alcance

- `config.py`: Mantener la validación actual de SESSION_SECRET en prod (RuntimeError si falta). Añadir, si se considera necesario, una comprobación de SITE_URL cuando billing esté activo (STRIPE_SECRET_KEY definido) o cuando haya redirecciones post-login que usen SITE_URL: en ese caso, si SITE_URL está vacío en prod, log CRITICAL y opcionalmente no arrancar (raise RuntimeError) o solo advertir. Decisión: documentar en la spec si es obligatorio o solo warning.
- `.env.example`: Incluir todas las variables usadas en config.py con comentarios que indiquen cuáles son obligatorias en producción (SESSION_SECRET, y SITE_URL si aplica) y cuáles opcionales. Valores de ejemplo no secretos.
- `LAUNCH_CHECKLIST.md`: Sección o ítems que listen las variables de entorno críticas para prod (SESSION_SECRET, SITE_URL si aplica, ENV=prod, STRIPE_* si se usa billing, etc.) y enlace a .env.example. Incluir cómo generar SESSION_SECRET (comando ya documentado en config).
- No cambiar la lógica de sesión ni de billing; solo validación en arranque y documentación.

---

## Fuera de alcance

- Validar otras variables (SMTP, Stripe keys más allá de existencia) en arranque.
- Cambiar el comportamiento de la app cuando las variables están definidas (solo validar al iniciar).
- Secrets en runtime (solo validación al cargar config).
- Migraciones o base de datos.

---

## Archivos a tocar

| Archivo / directorio | Cambio previsto |
|----------------------|-----------------|
| `config.py` | Opcional: después de cargar SITE_URL, si IS_PROD y (STRIPE_SECRET_KEY está definido o hay otra condición que requiera SITE_URL), comprobar que SITE_URL no esté vacío; si está vacío, logging.critical y opcionalmente raise RuntimeError con mensaje claro. Documentar en comentario. |
| `.env.example` | Listar SESSION_SECRET, SITE_URL, ENV, STRIPE_*, COOKIE_SECURE, etc. con comentarios: "Obligatorio en prod", "Requerido si usas billing", "Opcional". Incluir ejemplo de valor para SITE_URL (https://tudominio.com) y lugar para SESSION_SECRET (generar con: python3 -c "..."). |
| `LAUNCH_CHECKLIST.md` | Añadir sección "Variables de entorno en producción" con: SESSION_SECRET (obligatorio), ENV=prod, SITE_URL (obligatorio si billing), COOKIE_SECURE, referencia a .env.example. Incluir comando para generar SESSION_SECRET. |
| `README.md` o doc principal | Opcional: enlace a LAUNCH_CHECKLIST para despliegue en prod. |

---

## Reglas

1. En producción (ENV=prod), SESSION_SECRET debe seguir siendo obligatorio; si falta, la app no arranca (ya implementado en config.py). No relajar esta condición.
2. La validación de SITE_URL, si se añade, debe ser solo en prod y solo cuando sea razonable (ej. si STRIPE_SECRET_KEY está definido, entonces SITE_URL debería estar definido para redirects de Stripe). Si no se quiere bloquear arranque, usar logging.critical y continuar; si se quiere bloquear, raise RuntimeError con mensaje claro.
3. .env.example no debe contener valores reales de secretos; solo placeholders o instrucciones.
4. LAUNCH_CHECKLIST debe permitir a quien despliega comprobar que tiene todas las variables antes de arrancar en prod.

---

## Criterios de aceptación

- [ ] Con ENV=prod y sin SESSION_SECRET, la aplicación no arranca (RuntimeError). Comportamiento actual mantenido.
- [ ] Opcional: con ENV=prod, billing activo (STRIPE_SECRET_KEY definido) y SITE_URL vacío, la aplicación no arranca o registra CRITICAL con mensaje claro (según decisión de la spec).
- [ ] .env.example contiene las variables principales (SESSION_SECRET, ENV, SITE_URL, STRIPE_*, COOKIE_SECURE, etc.) con comentarios que indiquen obligatoriedad en prod.
- [ ] LAUNCH_CHECKLIST.md incluye la lista de variables críticas para producción y el comando para generar SESSION_SECRET.
- [ ] Un operador que siga LAUNCH_CHECKLIST y .env.example puede configurar un despliegue prod sin dejar variables críticas sin definir.

---

## Cómo probarlo manualmente

1. **Prod sin SESSION_SECRET:** Configurar ENV=prod y quitar SESSION_SECRET de .env. Arrancar la app; debe fallar con RuntimeError indicando SESSION_SECRET.
2. **Prod con SESSION_SECRET:** ENV=prod y SESSION_SECRET definido. La app debe arrancar.
3. **SITE_URL (si se implementó):** Con ENV=prod y STRIPE_SECRET_KEY definido, borrar SITE_URL. Arrancar; debe fallar o registrar CRITICAL según lo definido en la spec.
4. **Documentación:** Seguir LAUNCH_CHECKLIST en un entorno de prueba y verificar que todos los ítems de variables estén cubiertos. Revisar .env.example y comprobar que los comentarios sean correctos.

---

## Referencias

- AUDIT_README.md — Sección 5 (Seguridad), Job 8, Riesgos de producción.
- config.py — Validación actual de SESSION_SECRET, IS_PROD, SITE_URL, STRIPE_*.
- LAUNCH_CHECKLIST.md — Checklist de puesta en marcha.
