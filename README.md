# Conta Invoicing MVP

Aplicación de facturación y portal con integración SAT (CFDI).

---

## Database lifecycle

El schema de la base de datos se gestiona **solo por migraciones**. Al arrancar la app se ejecutan las migraciones pendientes sobre `invoicing.db` (o la ruta en `APP_DB_PATH`).

- **Crear/actualizar schema:** No hace falta ejecutar ningún script manual; las migraciones se aplican al iniciar la app.
- **Documentación completa:** [MIGRATIONS.md](MIGRATIONS.md) — cómo funciona el runner, cómo crear una migración nueva, cómo probar con DB desde cero o DB vieja, y qué hacer si aparecen errores WAL/SHM (`invoicing.db-wal`, `invoicing.db-shm`).

---

## Arranque

```bash
uvicorn app:app --reload
# o
./run_server.sh
```

Configuración opcional: `APP_DB_PATH`, `DEV_MODE`, `DEV_TOKEN` (ver `.env` o variables de entorno).

---

## Autenticación (portal)

El portal **no depende de `?token=` en la URL**. El token se usa solo para iniciar sesión una vez.

1. **Login:** Ir a `/login` e ingresar el token (o abrir `/login?token=TU_TOKEN`). Si el token es válido (`issuer_tokens`, `active=1`), se crea una sesión y se guarda una **cookie httpOnly** (`portal_session`). Redirige al portal sin token en la URL.
2. **Navegación:** Las rutas del portal y las APIs usan la cookie para identificar al emisor. No hace falta volver a pasar el token.
3. **Logout:** GET o POST `/logout` borra la cookie y redirige a la página pública.
4. **Compatibilidad:** Si alguien entra con `?token=...` en una URL del portal, se inicia sesión y se redirige a la misma ruta sin el token.

**Seguridad mínima:** Cookie con `HttpOnly`, `SameSite=Lax`, `Secure` según entorno (`COOKIE_SECURE=1` en producción). TTL configurable con `SESSION_TTL_DAYS` (por defecto 7). Se recomienda definir `SESSION_SECRET` en producción.

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
