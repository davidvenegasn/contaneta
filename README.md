# Conta Invoicing MVP

Aplicación de facturación y portal con integración SAT (CFDI).

---

## Database lifecycle

El schema de la base de datos se gestiona **solo por migraciones**. Al arrancar la app se ejecutan las migraciones pendientes sobre `invoicing.db` (o la ruta en `APP_DB_PATH`).

- **Crear/actualizar schema:** No hace falta ejecutar ningún script manual; las migraciones se aplican al iniciar la app.
- **Documentación completa:** [MIGRATIONS.md](MIGRATIONS.md) — cómo funciona el runner, cómo crear una migración nueva, cómo probar con DB desde cero o DB vieja, y qué hacer si aparecen errores WAL/SHM (`invoicing.db-wal`, `invoicing.db-shm`).
- **Operación:** [OPS_RUNBOOK.md](OPS_RUNBOOK.md) — deploy, backups, restore, health check, cron del worker SAT y logging.

---

## Arranque

```bash
uvicorn app:app --reload
# o
./run_server.sh
```

Configuración: ver sección **Variables de entorno** más abajo.

---

## Variables de entorno

| Variable | Uso | Recomendación |
|----------|-----|----------------|
| `APP_DB_PATH` | Ruta al archivo SQLite (por defecto `invoicing.db` en la raíz). | Opcional en desarrollo. |
| `DEV_MODE` | `1` = permite acceso demo sin cookie/token si existe emisor con `DEV_TOKEN`. | `0` en producción. |
| `DEV_TOKEN` | Token legacy para desarrollo (ej. `demo`). Debe existir en `issuer_tokens`. | Solo desarrollo; no exponer en producción. |
| `SESSION_SECRET` | Clave para firmar la cookie de sesión. | **Obligatorio en producción**; valor fuerte y secreto. |
| `SESSION_TTL_DAYS` | Días de validez de la cookie (por defecto 7). | Ajustar según política. |
| `COOKIE_SECURE` | `1` = cookie solo por HTTPS. | `1` en producción con HTTPS. |
| `FIRM_USER_EMAIL` | Email del usuario “firma” (admin interno). | Opcional. |
| `SITE_URL` | URL base del sitio (para OAuth y enlaces). | En producción con dominio propio. |
| `GOOGLE_CLIENT_ID` | OAuth Google (login con Google). | Opcional. |
| `FACEBOOK_APP_ID` | OAuth Facebook (login con Facebook). | Opcional. |

Registro y login usan **bcrypt** para el hash de contraseñas. El login tiene rate limit por IP (máx. 5 intentos por 60 s); el registro tiene límite de 3 intentos por 60 s por IP.

---

## Autenticación (portal)

El portal **no depende de `?token=` en la URL**. El token se usa solo para iniciar sesión una vez.

1. **Login:** Ir a `/login` e ingresar el token (o abrir `/login?token=TU_TOKEN`). Si el token es válido (`issuer_tokens`, `active=1`), se crea una sesión y se guarda una **cookie httpOnly** (`portal_session`). Redirige al portal sin token en la URL.
2. **Navegación:** Las rutas del portal y las APIs usan la cookie para identificar al emisor. No hace falta volver a pasar el token.
3. **Logout:** GET o POST `/logout` borra la cookie y redirige a la página pública.
4. **Compatibilidad:** Si alguien entra con `?token=...` en una URL del portal, se inicia sesión y se redirige a la misma ruta sin el token.

**Seguridad mínima:** Cookie con `HttpOnly`, `SameSite=Lax`, `Secure` según entorno (`COOKIE_SECURE=1` en producción). TTL configurable con `SESSION_TTL_DAYS` (por defecto 7). Se recomienda definir `SESSION_SECRET` en producción.

### Registro público

Cualquier persona puede crear cuenta en **`/register`**: correo, contraseña (mín. 8 caracteres), RFC, razón social, régimen fiscal y código postal (opcional). La app crea en la base:

- **users:** email (único), password_hash (bcrypt), nombre, active=1.
- **issuers:** RFC, razón social, régimen fiscal y un token legacy en `issuer_tokens` (para transición).
- **memberships:** un registro con `role = 'owner'` vinculando al usuario con el nuevo emisor.

Tras el registro se inicia sesión por cookie y se redirige a `/portal/home`; el portal opera sin token en la URL.

**Roles (memberships):** `owner` (cliente dueño del emisor), `admin` (superadministrador), `staff` (equipo), `viewer` (solo lectura), `accountant` (contador, legado).

### Token legacy (transición)

El acceso por **`/login?token=XXX`** sigue soportado: si el token existe en `issuer_tokens` y está activo, se crea sesión por cookie y se redirige al portal. No es necesario volver a pasar el token en la URL.

### Primera vez / sin usuarios (enlace para entrar)

Si aún no hay usuarios ni tokens en la base, crea un usuario demo y obtén el enlace directo:

```bash
python scripts/ensure_demo_user.py
```

El script crea un emisor "Usuario Demo (desarrollo)" con token `demo` (o el que definas en `DEV_TOKEN`) si no existe, e imprime el **enlace para entrar a ese usuario**:

- **Enlace directo al portal (ese usuario):** `http://127.0.0.1:8000/portal/home?token=demo`
- Con sesión: `http://127.0.0.1:8000/login?token=demo` → te redirige al portal y ya no necesitas el token en la URL.

Con `DEV_MODE=1`, si existe el usuario con token `demo`, también puedes ir directo a `http://127.0.0.1:8000/portal/home` (sin token) y entrarás como demo.

### Cómo probar en local

1. Arrancar la app: `uvicorn app:app --reload`
2. Si no hay usuarios: ejecutar `python scripts/ensure_demo_user.py` y usar el enlace que imprime.
3. Obtener un token válido (por ejemplo desde la base: `issuer_tokens.token` de un emisor activo).
4. Abrir en el navegador: `http://127.0.0.1:8000/login?token=TU_TOKEN` (o ir a `http://127.0.0.1:8000/login` y pegar el token en el formulario).
5. Tras el login serás redirigido a `/portal/home`. Navega por el portal: las URLs ya no llevan `?token=`.
6. Probar logout: en el menú de usuario (avatar/chevron) → "Cerrar sesión", o ir a `http://127.0.0.1:8000/logout`. Vuelve a `/`; si intentas entrar a `/portal/home` sin cookie, serás redirigido a `/login`.

**Nota:** Con `DEV_MODE=1`, si no hay cookie ni token, el portal permite entrar con un emisor demo (token `DEV_TOKEN`, por defecto `demo`) para facilitar desarrollo local — pero ese emisor debe existir en la base (creado con `ensure_demo_user.py`).

### Smoke test (registro, login y portal)

Prueba automatizada del flujo: **registro** (email + contraseña) → **confirmar perfil** (nombre + crear issuer) → **onboarding** (RFC y razón social) → **login** → **GET /portal/home**. Valida códigos de respuesta (200/302) y que la página del portal contenga el contenido esperado. Si algo falla, el script imprime en qué paso falló y un fragmento de la respuesta.

**Requisitos:** `requests` (incluido en `requirements.txt`). Servidor corriendo en `http://127.0.0.1:8000` o indicar otro puerto/URL.

```bash
# Con el servidor ya levantado (por defecto puerto 8000)
python3 scripts/smoke_onboarding.py

# Servidor en otro puerto
python3 scripts/smoke_onboarding.py --port 8010

# Arrancar el servidor temporalmente en 8010 y ejecutar el test
python3 scripts/smoke_onboarding.py --start-server --port 8010

# URL base explícita
python3 scripts/smoke_onboarding.py --base-url http://127.0.0.1:8000
```

Salida esperada si todo va bien: `OK. Smoke onboarding: registro → confirmar perfil → onboarding (RFC) → login → /portal/home.`

---

## Impersonación (solo admin)

Los usuarios con **rol `admin`** en alguna membership pueden “entrar como” otro emisor (por `issuer_id` o `rfc`). Toda acción queda registrada en `audit_log`.

### Permisos

- **Solo rol `admin`** puede impersonar. Los usuarios con rol `owner`, `staff` o `viewer` no pueden (403).
- En Panel Admin → Issuers solo los admin ven el botón "Entrar como"; la búsqueda por RFC/razón social/email está disponible para admin y owner.

### Cómo desactivar la impersonación

- En la base: quitar el rol admin de memberships, por ejemplo `UPDATE memberships SET role = 'owner' WHERE role = 'admin';`
- No asignar `role = 'admin'` a nadie si no quieres que nadie pueda impersonar.

### Auditoría

En `audit_log` se registran: `login`, `logout`, `impersonate`, `stop_impersonate`, `download_xml`, `download_pdf`, `cfdi_view`, `register`, `admin_ops`, etc. La tabla incluye columnas `entity`, `entity_id`, `meta_json`, `ip`, `user_agent` (migración 011). Cualquier trigger de sync SAT debería llamar a `audit.log(action="sync_sat_trigger", ...)`.

### Seguridad

- Solo usuarios con al menos una membership con `role = 'admin'` pueden usar la impersonación.
- Cualquier uso de impersonación (entrar y salir) se registra en la tabla `audit_log` (acción `impersonate` o `stop_impersonate`).

### Pasos manuales para probar

1. **Tener un usuario admin**  
   En la base, asigna rol `admin` a un usuario en alguna membership:
   ```sql
   -- Ejemplo: dar rol admin al usuario con id 1 en el issuer 1
   UPDATE memberships SET role = 'admin' WHERE user_id = 1 AND issuer_id = 1;
   ```
   (Si la tabla no tiene filas, crea antes un usuario y una membership con `INSERT` en `users` y `memberships`.)

2. **Iniciar sesión como ese usuario**  
   Login normal (email/teléfono + contraseña o token) y que la sesión sea para un issuer donde ese usuario tenga rol `admin`.

3. **Impersonar**  
   Desde el panel Admin → Issuers: clic en **"Entrar como"** (enlace a `GET /admin/impersonate/{issuer_id}`). O por API:  
   - Por **issuer_id**:
     ```bash
     curl -X POST http://127.0.0.1:8000/admin/impersonate \
       -H "Content-Type: application/json" \
       -d '{"issuer_id": 2}' \
       -c cookies.txt -b cookies.txt -L
     ```
   - Por **rfc**:
     ```bash
     curl -X POST http://127.0.0.1:8000/admin/impersonate \
       -H "Content-Type: application/json" \
       -d '{"rfc": "XAXX010101000"}' \
       -c cookies.txt -b cookies.txt -L
     ```
   Debes haber hecho antes login y guardado la cookie en `cookies.txt` (por ejemplo con un login vía `curl` o desde el navegador y exportar cookies). La respuesta es una **redirección 302 a `/portal/home`**; al seguirla verás el portal del emisor suplantado.

4. **Comprobar en el portal**  
   En el portal debe verse el nombre/alias del emisor suplantado y el banner “Estás viendo el portal como **&lt;emisor&gt;**” con el enlace **“Volver a mi cuenta”**.

5. **Salir de la impersonación**  
   - En la UI: clic en **“Volver a mi cuenta”** (en el banner o en el menú de usuario).  
   - O por API:
     ```bash
     curl -X POST http://127.0.0.1:8000/admin/stop-impersonate -b cookies.txt -L
     ```
   Tras esto se restaura la sesión a tu emisor original y se redirige a `/portal/home`.

6. **Verificar auditoría**  
   En la base:
   ```sql
   SELECT * FROM audit_log WHERE action IN ('impersonate', 'stop_impersonate') ORDER BY created_at DESC;
   ```
   Deben aparecer filas con `action = 'impersonate'` (al entrar como otro emisor) y `action = 'stop_impersonate'` (al volver a tu cuenta).

### Tests rápidos (manual)

| Paso | Acción | Resultado esperado |
|------|--------|--------------------|
| 1 | Usuario sin rol admin hace POST `/admin/impersonate` con body `{"issuer_id": 2}` | 403 Solo administradores |
| 2 | Usuario admin hace POST `/admin/impersonate` con `{"issuer_id": id_inexistente}` | 400 Issuer no encontrado |
| 3 | Usuario admin hace POST `/admin/impersonate` con `{"issuer_id": N}` (válido) | 302 → `/portal/home`, portal del issuer N |
| 4 | En portal, comprobar banner y menú | Banner “Estás viendo el portal como …” y opción “Volver a mi cuenta” |
| 5 | Clic en “Volver a mi cuenta” o POST `/admin/stop-impersonate` | 302 → `/portal/home`, portal del emisor original |
| 6 | Consultar `audit_log` | Filas `impersonate` y `stop_impersonate` con `user_id` del admin y `target_issuer_id` correcto |
