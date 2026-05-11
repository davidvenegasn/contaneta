# Resumen de implementaciones previas (antes de esta sesión)

Resumen de las funcionalidades que se implementaron automáticamente en sesiones anteriores.

---

## 1. Sistema completo de registro e inicio de sesión

### Registro (`/signup`)
- **Registro con correo o teléfono** + contraseña
- **Registro con Google** (OAuth) - si está configurado `GOOGLE_CLIENT_ID`
- **Registro con Facebook** (OAuth) - si está configurado `FACEBOOK_APP_ID`
- Validación de contraseña (mínimo 8 caracteres)
- Checkbox de términos y condiciones
- Opción de autorizar al despacho fiscal (V&G Fiscal) durante el registro

### Login (`/login`)
- Entrar con **correo o teléfono** + contraseña
- Entrar con **Google** o **Facebook** (si están configurados)
- Entrar con **token** (sistema legacy: `/login?token=XXX`)
- Rate limiting: máximo 5 intentos por IP cada 60 segundos

### Base de datos
- Tabla `users`: almacena email, teléfono, hash de contraseña, datos OAuth
- Tabla `memberships`: relación usuario-issuer con roles (`owner`, `accountant`, `viewer`)
- Un usuario puede tener acceso a múltiples empresas (issuers)

**Archivos relacionados:**
- `routers/auth.py` - Rutas de signup y login
- `services/users.py` - Gestión de usuarios y contraseñas
- `services/session.py` - Gestión de cookies de sesión
- Migración 005: creación de tablas `users` y `memberships`

---

## 2. Verificación de email

### Funcionalidad
- Al registrarse, se envía un correo con un enlace de verificación
- El enlace tiene un token único que expira en 24 horas
- Los tokens se guardan como **hash** en la base de datos (nunca en texto plano)
- Si el token es válido, se marca como usado y el email queda verificado

### Rutas
- `GET /verify-email?token=XXX` - Verifica el email y redirige a login

### Base de datos
- Tabla `email_verifications`: almacena tokens hasheados, fecha de expiración, fecha de uso

**Archivos relacionados:**
- `services/verification.py` - Creación y verificación de tokens
- `services/email_sender.py` - Envío de correos (SMTP o log en DEV)
- `routers/auth.py` - Ruta `/verify-email`
- Migración 012: creación de tabla `email_verifications`

---

## 3. Recuperación de contraseña (Forgot Password / Reset Password)

### Funcionalidad
- Página "¿Olvidaste tu contraseña?" (`/forgot`)
- El usuario ingresa su correo
- Se envía un correo con un enlace para restablecer contraseña
- El token expira en 2 horas
- Los tokens se guardan como **hash** (nunca en texto plano)
- El usuario puede establecer una nueva contraseña

### Rutas
- `GET /forgot` - Página "Recuperar contraseña"
- `POST /forgot` - Envía el correo con el enlace de reset
- `GET /reset-password?token=XXX` - Página para establecer nueva contraseña
- `POST /reset-password` - Actualiza la contraseña

### Seguridad
- Rate limiting: máximo 3 solicitudes por IP cada 60 segundos
- Tokens de un solo uso (se marcan como usados al consumirse)
- Tokens con expiración corta (2 horas)

**Archivos relacionados:**
- `services/verification.py` - Creación y consumo de tokens de reset
- `services/email_sender.py` - Envío del correo con enlace
- `routers/auth.py` - Rutas `/forgot` y `/reset-password`
- `templates/forgot_password.html` - Página de solicitud
- `templates/reset_password.html` - Página de nueva contraseña
- Migración 012: creación de tabla `password_resets`

---

## 4. Onboarding (Completar perfil fiscal)

### Funcionalidad
- Después de registrarse, el usuario debe completar su perfil fiscal
- Campos: RFC, Razón social, Régimen fiscal, Código postal (opcional)
- Opción de autorizar al despacho fiscal durante el onboarding
- Una vez completado, se crea el `issuer` y se asigna al usuario como `owner`

### Rutas
- `GET /onboarding` - Página de completar perfil
- `POST /onboarding` - Guarda los datos fiscales y crea el issuer

**Archivos relacionados:**
- `routers/auth.py` - Rutas de onboarding
- `templates/onboarding.html` - Formulario de datos fiscales

---

## 5. Elección de empresa (Choose Issuer)

### Funcionalidad
- Si un usuario tiene acceso a múltiples empresas (issuers), al hacer login se muestra una página para elegir con cuál entrar
- Lista todas las empresas a las que tiene acceso
- Una vez elegida, se guarda en la sesión y entra al portal

### Rutas
- `GET /choose-issuer` - Página de selección
- `POST /choose-issuer` - Guarda la selección y redirige al portal

**Archivos relacionados:**
- `routers/auth.py` - Rutas de choose-issuer
- `templates/choose_issuer.html` - Lista de empresas disponibles

---

## 6. Sistema de envío de correos

### Funcionalidad
- Si `SMTP_HOST`, `SMTP_USER` y `SMTP_PASSWORD` están configurados: envía correos reales por SMTP
- Si no hay SMTP configurado y `DEV_MODE=1`: loguea el contenido del correo en los logs del servidor (para ver los enlaces de verificación/reset en desarrollo)

### Variables de entorno necesarias
- `SMTP_HOST` - Servidor SMTP (ej. `smtp.gmail.com`)
- `SMTP_PORT` - Puerto SMTP (ej. `587`)
- `SMTP_USER` - Usuario SMTP
- `SMTP_PASSWORD` - Contraseña SMTP
- `SMTP_FROM` - Email remitente (opcional, usa `SMTP_USER` por defecto)

**Archivos relacionados:**
- `services/email_sender.py` - Lógica de envío SMTP o log en DEV

---

## 7. OAuth (Google y Facebook)

### Funcionalidad
- Botones de "Continuar con Google" y "Continuar con Facebook" en signup y login
- Solo se muestran si las credenciales OAuth están configuradas
- Si el usuario ya existe (por email), se vincula la cuenta OAuth
- Si no existe, se crea un nuevo usuario

### Configuración necesaria
- **Google**: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SITE_URL`
- **Facebook**: `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET`, `SITE_URL`

**Archivos relacionados:**
- `routers/auth.py` - Callbacks OAuth (`/auth/google/callback`, `/auth/facebook/callback`)

---

## 8. Seguridad implementada

### Rate limiting
- **Login**: máximo 5 intentos por IP cada 60 segundos
- **Registro**: máximo 3 intentos por IP cada 60 segundos
- **Forgot password**: máximo 3 solicitudes por IP cada 60 segundos

### Tokens seguros
- Todos los tokens (verificación de email, reset de contraseña) se guardan como **hash SHA256** en la base de datos
- Nunca se almacenan en texto plano
- Tokens de un solo uso (se marcan como usados al consumirse)
- Tokens con expiración (24h para verificación, 2h para reset)

### CSRF protection
- Todos los formularios tienen tokens CSRF para prevenir ataques

**Archivos relacionados:**
- `services/csrf.py` - Generación y verificación de tokens CSRF
- `routers/auth.py` - Rate limiting y validación CSRF en todas las rutas

---

## Migraciones de base de datos aplicadas

1. **Migración 005**: Creación de `users` y `memberships`
2. **Migración 012**: Creación de `email_verifications` y `password_resets`

---

## Resumen en una frase

Se implementó un sistema completo de autenticación con registro (email/teléfono/OAuth), verificación de email, recuperación de contraseña, onboarding fiscal, y gestión de múltiples empresas por usuario, todo con seguridad (rate limiting, tokens hasheados, CSRF).
