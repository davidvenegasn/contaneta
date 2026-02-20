# Seguridad — ContaNeta

Medidas implementadas y checklist antes de lanzamiento público.

---

## 1. Rate limiting

- **Login:** Máximo 5 intentos por IP en 60 segundos. Tras superar el límite se aplica un retraso y se devuelve mensaje genérico ("Datos inválidos").
- **Registro:** Máximo 3 intentos por IP en 60 segundos. Reduce abuso de creación de cuentas.

---

## 2. Protección CSRF

- **Token firmado:** En POSTs sensibles se exige un token CSRF generado por el servidor (firmado con HMAC, validez 1 hora).
- **Rutas protegidas:** Login (`/login`), registro (`/auth/register`), elegir issuer (`/choose-issuer`), envío de factura (`/submit`).
- **Flujo:** Al servir el formulario (GET) se genera el token y se incluye en un campo oculto; al enviar el POST se verifica firma y caducidad. Si falla, se responde 400 o redirección.

---

## 3. Cookies seguras

- **HttpOnly:** La cookie de sesión tiene `httponly=True` (no accesible desde JavaScript).
- **SameSite:** `lax` para reducir riesgo de CSRF desde otros sitios.
- **Secure:** En producción debe usarse `COOKIE_SECURE=1` para que la cookie solo se envíe por HTTPS. Si el proxy indica `X-Forwarded-Proto: https`, se fuerza Secure.
- **TTL:** `SESSION_TTL_DAYS` (por defecto 7). La cookie tiene `max_age = SESSION_TTL_DAYS * 86400` segundos.

---

## 4. Validación de issuer_id

- **Origen del issuer:** En rutas del portal y de la API, el `issuer_id` usado en consultas viene siempre de la dependencia `get_portal_issuer` (sesión o token), no de parámetros de URL o body.
- **Consultas:** Todas las consultas que filtran por datos de cliente incluyen `WHERE issuer_id = ?` con el issuer de la sesión. No se usa un `issuer_id` llegado del cliente sin comprobar membresía.
- **Elegir issuer:** En `POST /choose-issuer` se valida con `get_membership(user_id, issuer_id)` que el usuario tenga acceso al issuer elegido.

---

## 5. Sanitización de inputs

- **Email:** Lowercase, trim, longitud máxima (p. ej. 254). Módulo `services/sanitize`.
- **RFC:** Solo mayúsculas y alfanuméricos, longitud máxima 13.
- **Código postal:** Solo dígitos; longitud 5 para México.
- **Montos:** Conversión a float no negativo; en formularios se aceptan decimales.

Se usan en registro (email, rfc, cp) y pueden aplicarse en más formularios según necesidad.

---

## 6. Otros

- **Path traversal:** Las rutas que sirven XML/PDF resuelven rutas bajo `BASE_DIR` y rechazan paths que salgan del árbol (`_safe_abs_path`).
- **Contraseñas:** Siempre hash con bcrypt; no se almacenan en claro.
- **Mensajes de error:** En login y registro se usan mensajes genéricos para no revelar si un email existe o no.

---

## Checklist antes de producción

- [ ] **COOKIE_SECURE=1** en el entorno de producción.
- [ ] **SESSION_SECRET** aleatorio y distinto por entorno (no el default en prod).
- [ ] **DEV_MODE=0** en producción.
- [ ] HTTPS en todo el sitio (proxy inverso con TLS).
- [ ] Variables de Stripe (billing) con claves de producción si se usan pagos.
- [ ] Revisar que no queden credenciales o secretos en el código o en logs.
- [ ] Backups programados (DB y storage) y probada la restauración.
- [ ] Endpoint `/health` monitorizado; alertas si `status != ok`.
- [ ] Rate limiting y CSRF activos (por defecto lo están).
- [ ] Logs de auditoría (`audit_log`) revisables para acciones sensibles.
