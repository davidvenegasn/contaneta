# Configuración de registro e inicio de sesión

## Qué se implementó

- **Signup** (`/signup`): registro con **correo o teléfono** + contraseña, o con **Google** / **Facebook**.
- **Login** (`/login`): entrar con correo/teléfono + contraseña, con Google/Facebook, o con **token** (legacy).
- **Onboarding** (`/onboarding`): tras registrarse, el usuario completa RFC, razón social, régimen y CP; opción de autorizar al despacho.
- **Sesión**: se guarda `user_id` + `issuer_id` en cookie; si el usuario tiene varios RFC, se muestra **elegir empresa** (`/choose-issuer`).
- **Despacho**: si en signup/onboarding marcan "Autorizo a V&G Fiscal...", se agrega al usuario del despacho como **accountant** de ese issuer (variable `FIRM_USER_EMAIL`).
- **Legales**: `/terms` y `/privacy` (textos MVP).

## Base de datos (migración 005)

- **users**: `id`, `email`, `phone`, `password_hash`, `oauth_provider`, `oauth_id`, `created_at`. Un usuario se identifica por email, teléfono o (oauth_provider, oauth_id).
- **memberships**: `user_id`, `issuer_id`, `role` (`viewer` | `accountant` | `owner`), `created_at`. Relación usuario–issuer con rol.

## Variables de entorno

| Variable | Uso |
|----------|-----|
| `FIRM_USER_EMAIL` | Correo del usuario “despacho” (V&G Fiscal). Si el cliente autoriza en signup/onboarding, se crea una membership con rol `accountant` para este usuario en el issuer del cliente. Debe existir un user con ese email (creado por signup o por ti en BD). |
| `SITE_URL` | URL base para callbacks OAuth (ej. `https://tudominio.com`). Si no se define, se usa la URL de la petición (puede fallar en producción con proxy). |
| `GOOGLE_CLIENT_ID` | Para “Continuar con Google”. Si no está, el botón apunta a `#`. |
| `GOOGLE_CLIENT_SECRET` | Secreto de la app Google (OAuth). |
| `FACEBOOK_APP_ID` | Para “Continuar con Facebook”. |
| `FACEBOOK_APP_SECRET` | Secreto de la app Facebook. |
| `DEMO_ISSUER_ID` | ID del issuer de demostración (portal con datos de ejemplo). Si no está definido, en DEV_MODE se usa el issuer del token demo. |

## OAuth (Google / Facebook)

Los botones **solo se muestran** cuando las variables están configuradas (solo verás los logos de Google y Facebook si hay acceso real).

1. **Google** (nombre, apellidos y opcionalmente teléfono)
   - El flujo pide scope de perfil (nombre) y de teléfono (`user.phonenumbers.read`). Si el usuario no tiene teléfono en su cuenta Google o no autoriza, el teléfono queda vacío.
   - En [Google Cloud Console](https://console.cloud.google.com/) crea un proyecto.
   - Activa **People API** si quieres intentar obtener teléfono (opcional; a veces requiere verificación de la app).
   - “APIs y servicios” → “Credenciales” → “Crear credenciales” → “ID de cliente OAuth 2.0”.
   - Tipo: “Aplicación web”.
   - En **“URIs de redirección autorizados”** agrega exactamente (según dónde corras la app):
     - Local: `http://127.0.0.1:8000/auth/google/callback`
     - Producción: `https://tudominio.com/auth/google/callback`
   - Copia el **ID de cliente** y el **Secreto del cliente** a tu `.env` como `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET`.
   - Si usas producción, define también `SITE_URL=https://tudominio.com`.

2. **Facebook**
   - En [Facebook for Developers](https://developers.facebook.com/) crea una app y añade el producto “Facebook Login”.
   - En Facebook Login → “Configuración” → “URIs de redirección de OAuth válidos” agrega:
     - Local: `http://127.0.0.1:8000/auth/facebook/callback`
     - Producción: `https://tudominio.com/auth/facebook/callback`
   - Copia **ID de la aplicación** y **Secreto de la aplicación** a `.env` como `FACEBOOK_APP_ID` y `FACEBOOK_APP_SECRET`.
   - En producción, define `SITE_URL=https://tudominio.com`.

## Crear el usuario despacho

Para que `FIRM_USER_EMAIL` funcione, debe existir un usuario con ese email:

- Opción 1: registrarte en `/signup` con ese correo (y completar onboarding con un RFC de prueba si quieres).
- Opción 2: insertar en BD (después de tener passlib):  
  `INSERT INTO users (email, password_hash, created_at) VALUES ('tu@despacho.com', '<hash generado por passlib>', datetime('now'));`

## Clientes que tú des das de alta

Puedes crear usuarios manualmente (por script o en BD): `users` con email/teléfono y `password_hash` (usa la misma función de hash que en signup). Luego creas el `issuer` y una `membership` con `role = 'owner'` para ese user. Les das la contraseña inicial; ellos pueden cambiarla cuando implementes “Cambiar contraseña” en el portal.

## Dependencias nuevas

En `requirements.txt` se añadieron:

- `passlib[bcrypt]` para contraseñas.
- `httpx` para llamadas OAuth (intercambio de código por token y obtención de perfil).

Instalar: `pip install -r requirements.txt` (o tu gestor de entornos).
