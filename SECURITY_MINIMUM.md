# Mínimos de seguridad para lanzamiento público

Documento de referencia para el despliegue en producción. No sustituye una auditoría de seguridad.

## 1. CSRF (Cross-Site Request Forgery)

- **Token por sesión/página:** Todas las peticiones POST que cambian estado (login, registro, forgot, reset, admin ops, impersonación, subida FIEL) exigen un token CSRF.
- **Formularios:** Incluir `<input type="hidden" name="csrf_token" value="{{ csrf_token }}" />` en cada form POST.
- **Fetch/AJAX:** Enviar el token en cabecera `X-CSRF-Token`. El token está disponible en `<meta name="csrf-token" content="...">` en el HTML del portal.
- **Validación:** El backend verifica el token (formulario o cabecera) y responde 403 si es inválido o expirado (vida típica 1 hora).

## 2. Cabeceras de seguridad (middleware)

Aplicadas en todas las respuestas cuando no están ya definidas:

| Cabecera | Valor / descripción |
|----------|---------------------|
| **X-Content-Type-Options** | `nosniff` — evita MIME sniffing |
| **X-Frame-Options** | `DENY` — no permitir embedding en iframes |
| **Content-Security-Policy** | CSP básico: `default-src 'self'`, `frame-ancestors 'none'`, orígenes permitidos para Stripe y Google Fonts |
| **Referrer-Policy** | `strict-origin-when-cross-origin` |
| **Permissions-Policy** | Restricción de geolocation, microphone, camera, payment, usb, serial |

## 3. Rate limiting

- **Auth (login, registro, forgot, reset):** Por IP, máx. 10 intentos por minuto; cooldown por email tras fallos de login.
- **FIEL / SAT:** Por IP, máx. 10 peticiones por minuto en:
  - Subida de credenciales (`/portal/config/sat` POST)
  - Validación FIEL (`/portal/config/sat/validate`)
  - Disparo de sincronización SAT (`/portal/sat/sync`)

Respuesta ante límite superado: **429** con mensaje tipo "Demasiados intentos. Espera un minuto."

## 4. Variables de entorno críticas

Ver `.env.example`. En producción son obligatorias o muy recomendadas:

- **SESSION_SECRET** — Obligatorio en prod; valor estable y aleatorio (p. ej. `secrets.token_hex(32)`).
- **ENV=prod** — Activa defaults seguros (cookie Secure, etc.).
- **COOKIE_SECURE=1** — Si se sirve por HTTPS.
- **APP_DB_PATH** — Ruta absoluta a la base de datos.

No subir `.env` al repositorio.

## 5. Auditoría

- Acciones sensibles (impersonación, subida FIEL, login, etc.) se registran en `audit_log` con `action`, `user_id`, `issuer_id`, `ip`, `user_agent` cuando se dispone de `request`.

## 6. Resumen de comprobaciones pre-lanzamiento

- [ ] `ENV=prod`, `SESSION_SECRET` definido, `COOKIE_SECURE=1` si hay HTTPS.
- [ ] No usar `ALLOW_DEMO_PORTAL=1` ni `DEV_MODE=1` en producción.
- [ ] Revisar que los formularios sensibles incluyan `csrf_token` y que los fetch envíen `X-CSRF-Token`.
- [ ] Confirmar que el middleware de security headers está activo (cabeceras visibles en respuestas).
- [ ] Probar rate limit en login y en FIEL/sync (esperar 429 tras superar límite).
