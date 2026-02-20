# Decisiones de diseño y operación

Documento de decisiones tomadas para lanzamiento público y operación autónoma.

---

## Autenticación y registro

- **Registro autónomo:** Un usuario nuevo se registra en `/register` con email, contraseña, RFC, razón social y régimen fiscal. Se crea `user`, `issuer`, `issuer_token` y `membership(owner)` en una sola transacción lógica; se inicia sesión por cookie y se redirige a `/portal/home`. No se exige paso intermedio (confirmar-perfil/onboarding) para entrar al portal.
- **Token legacy:** El acceso por `?token=...` sigue funcionando: el middleware y `get_portal_issuer` aceptan token en query; si es válido, se firma una cookie y se elimina el token de la URL. Recomendado para producción: registro + login por email/contraseña; el token queda como fallback para enlaces compartidos.
- **Contraseñas:** Siempre hash con bcrypt (services/users.py). No se almacena contraseña en texto plano.
- **Mensajes de error:** En login y registro se usan mensajes genéricos (“Datos inválidos”, “No se pudo crear la cuenta”) para no revelar si un email existe o no.

---

## Roles y acceso

- **Roles en `memberships`:** `viewer`, `accountant`, `owner`, `admin`. El registro crea solo `owner`. Admin se asigna manualmente (p. ej. `UPDATE memberships SET role = 'admin' WHERE user_id = X AND issuer_id = Y`) para impersonación y operaciones sensibles.
- **Impersonación:** Solo usuarios con rol `admin` en alguna membership pueden usar `/admin/impersonate` y `/admin/stop-impersonate`. Cada acción se registra en `audit_log`.

---

## Auditoría

- **Tabla `audit_log`:** Acciones registradas: `login`, `logout`, `impersonate`, `stop_impersonate`, `download_xml`, `download_pdf`, `quotation_pdf`. Incluyen `user_id`, `issuer_id`, `target_issuer_id` (si aplica) y `details`.
- **Separación por issuer:** Todas las rutas del portal y APIs que devuelven datos usan `issuer_id` de la sesión (o token); las queries filtran por `issuer_id` para no mezclar datos entre clientes.

---

## Operación y backups

- **Health:** `GET /health` devuelve `{"status": "ok"|"degraded", "db": "ok"|"error"}`. No requiere autenticación. Uso: balanceadores y monitoreo.
- **Backups:** Scripts no destructivos:
  - `scripts/backup_db.sh`: copia `invoicing.db` a `backup/invoicing_YYYYMMDD_HHMMSS.db`.
  - `scripts/backup_storage_xml.sh`: copia el directorio `storage` a `backup/storage_YYYYMMDD_HHMMSS`.
  - `scripts/cron_backup_example.sh`: ejemplo de entradas cron; no ejecuta backups por sí solo.
- **Retención:** La limpieza de backups antiguos (p. ej. borrar copias de más de 30 días) se deja fuera de estos scripts para no hacer operaciones destructivas automáticas sin configuración explícita.

---

## Seguridad adicional

- **Rate limit login:** Hasta 5 intentos de login por IP en una ventana de 60 segundos; tras superar el límite se aplica un retraso y se devuelve error genérico.
- **Path traversal:** Las rutas que sirven XML/PDF resuelven rutas bajo `BASE_DIR` y rechazan paths que salgan de ese árbol (`_safe_abs_path`).

---

*Última actualización: lanzamiento público / hardening autónomo.*
