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
- **Impersonación:** Solo usuarios con rol `admin` u `owner` en alguna membership pueden usar el panel admin y `/admin/impersonate` / `/admin/stop-impersonate`. Cada acción se registra en `audit_log` (incluyendo IP y user-agent en `details` para impersonate).

---

## Auditoría

- **Tabla `audit_log`:** Acciones registradas: `register`, `login`, `logout`, `impersonate`, `stop_impersonate`, `download_xml`, `download_pdf`, `quotation_pdf`, `cfdi_view`, `admin_ops`. Incluyen `user_id`, `issuer_id`, `target_issuer_id` (si aplica) y `details`. Para impersonate se guardan IP y user-agent en `details`.
- **Sync SAT:** El sincronizado con SAT se dispara por scripts externos (sat_sync/*); si en el futuro la app expone un endpoint de sync, se registrará en audit_log.
- **Separación por issuer:** Todas las rutas del portal y APIs que devuelven datos usan `issuer_id` de la sesión (o token); las queries filtran por `issuer_id` para no mezclar datos entre clientes.

---

## Operación y backups

- **Health:** `GET /health` devuelve JSON con `ok`, `db_readable`, `migrations_applied`, `migration_version` (última aplicada), `storage_writable`. No requiere autenticación. Pensado para balanceadores y monitoreo 24/7.
- **Backups:** Scripts con rotación opcional:
  - `scripts/backup_db.sh`: copia `invoicing.db` a `backup/` con timestamp; mantiene últimos `BACKUP_RETAIN_DAYS` días (default 30).
  - `scripts/backup_storage.sh`: copia `storage/` a `backup/` con timestamp y misma rotación.
  - Restaurar: ver `scripts/restore_notes.md`.
- **Despliegue:** Guía paso a paso en DEPLOY_GUIDE.md (usuario, venv, .env, migraciones, systemd, Nginx/Caddy, HTTPS Let's Encrypt, cron backups). Servicio systemd con Restart=always para que reinicie solo.

---

## Billing (suscripciones Stripe)

- **Modelo:** Tabla `subscriptions` (user_id, plan, status, stripe_customer_id, stripe_subscription_id, current_period_end). Un registro por usuario (UNIQUE user_id). Status: active, canceled, past_due, trialing, inactive, incomplete.
- **Checkout:** `POST /billing/checkout` crea una sesión de Stripe Checkout (subscription) y devuelve `{ "url": "..." }`. Requiere sesión con user_id > 0. El frontend redirige a esa URL.
- **Webhook:** `POST /webhooks/stripe` recibe checkout.session.completed (activar suscripción), customer.subscription.updated (actualizar estado/periodo) y customer.subscription.deleted (marcar canceled). Firma verificada con STRIPE_WEBHOOK_SECRET.
- **Gating:** Usuarios con suscripción no activa (status distinto de active/trialing) reciben 402 en descarga XML y descarga PDF; el resto del portal sigue usable. Usuarios solo por token (user_id 0) no se comprueba suscripción para no romper enlaces legacy.
- **Configuración:** STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_ID, SITE_URL. Detalle en BILLING_GUIDE.md.

---

## Seguridad (agent/security)

- **Rate limiting:** Login: 5 intentos por IP en 60 s. Registro: 3 intentos por IP en 60 s. Retraso y mensaje genérico al superar el límite.
- **CSRF:** Token firmado (HMAC, validez 1 h) en login, registro, choose-issuer y submit de factura. Verificación en cada POST sensible.
- **Cookies:** HttpOnly, SameSite=Lax, Secure en prod (COOKIE_SECURE=1 o X-Forwarded-Proto: https), max_age=SESSION_TTL_DAYS. Ver services/session.session_cookie_params.
- **issuer_id:** Siempre obtenido de get_portal_issuer (sesión/token). Todas las consultas que filtran datos de cliente incluyen WHERE issuer_id = ?. choose-issuer valida membresía antes de cambiar issuer.
- **Sanitización:** services/sanitize: email (lower, longitud), RFC (alfanumérico, mayúsculas), CP (sólo dígitos, 5), montos (float no negativo). Aplicado en registro y reutilizable en otros formularios.
- **Path traversal:** Rutas XML/PDF con _safe_abs_path bajo BASE_DIR.
- **Checklist antes de prod:** Ver SECURITY.md.

---

---

## Panel admin (CONTRATO 3)

- **Acceso:** Rutas bajo `/admin` (dashboard, users, issuers, memberships, ops) exigen sesión y rol `admin` u `owner` vía `user_has_admin_or_owner_role(user_id)`.
- **Dashboard:** Tarjetas con conteos (users, issuers, memberships), sat_cfdi por dirección y mes actual, sat_requests por status, últimos 20 audit_log.
- **Impersonación:** Botón “Entrar como este issuer” en `/admin/issuers` (POST a `/admin/impersonate-form`). Se registra en audit_log con IP y user-agent en `details`. En el portal se muestra banner “Modo soporte: estás viendo como X” y botón “Salir de soporte” (POST `/admin/stop-impersonate`).
- **Status/Health admin:** `GET /admin/status` y `GET /admin/health` muestran conteos: #usuarios, #issuers, #CFDI por estado, #jobs pendientes. Requieren rol admin u owner.
- **Ops:** `/admin/ops` permite “Correr migraciones” (apply_migrations), “Verificar DB” (listado de tablas y schema_migrations), “Crear backup ahora” (scripts backup_db.sh y backup_storage_xml.sh). Cada acción se registra en audit_log.

*Última actualización: audit register/cfdi_view, /admin/status con conteos, Salir de soporte (agent/admin-ops).*
