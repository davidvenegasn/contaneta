# Auditoría de sesión y autenticación — Vuelta al issuer demo/default

**Objetivo:** Diagnosticar por qué a veces la navegación muestra el issuer demo en lugar de redirigir a `/login`. Solo diagnóstico; sin cambios de UI/CSS ni features nuevas.

---

## Resumen ejecutivo

- **Con `DEV_MODE=0`** el código **nunca** devuelve demo ante cookie inválida/expirada: el middleware redirige a `/login` o `get_portal_issuer` lanza 401 y el manejador global redirige a `/login`. El problema observable (“a veces vuelve al demo”) ocurre cuando **`DEV_MODE` no está en 0** (p. ej. en producción no se define y por defecto es `"1"`).
- **Causa principal:** En `config.py`, `DEV_MODE` tiene default `"1"`. Si en producción no se define `DEV_MODE=0`, cualquier petición sin sesión válida (cookie ausente, inválida o expirada) pasa el middleware y cae en el fallback demo de `get_portal_issuer`.
- **Fix recomendado:** Cambiar el default de `DEV_MODE` en **`config.py`** para que, cuando `ENV=prod`, sea `"0"` si no está definido; así en prod no se usa el fallback a demo por defecto.

---

## 1. Ubicación de `get_portal_issuer` y flujo de cookie

### 1.1 Dónde está

- **`get_portal_issuer`:** `routers/deps.py`, función `get_portal_issuer(request)` (líneas 8–81). Es una dependencia FastAPI que devuelve el `issuer` para rutas del portal.
- **Cookie de sesión:** nombre en `config.SESSION_COOKIE_NAME` (`portal_session`). Valor firmado y con expiry en `services/session.py` (`sign_session` / `verify_session`). Parámetros de cookie (HttpOnly, SameSite, Secure) en `session.session_cookie_params(request)`.

### 1.2 Flujo de la cookie (orden en código)

1. **Middleware** (`app.py`, `redirect_token_middleware`, ~257–264): solo para rutas portal HTML sin `?token=`. Lee `request.cookies.get(SESSION_COOKIE_NAME)`, llama `session.verify_session(cookie_val)`. Si `session_data is None and not DEV_MODE` → `RedirectResponse(url="/login")`. Si no redirige, la petición sigue.
2. **Ruta que usa `get_portal_issuer`** (p. ej. páginas HTML del portal): se ejecuta `get_portal_issuer(request)`.
3. **Dentro de `get_portal_issuer`** (`routers/deps.py`):
   - Si hay `?token=` válido → se devuelve ese issuer (y se ignora la cookie para esa petición).
   - Si no: `cookie_val = request.cookies.get(cookie_name)`, `session_data = session.verify_session(cookie_val)`.
   - Si `session_data is not None`: se valida issuer y membresía; si todo OK se devuelve el issuer; si issuer no existe o no hay membresía, no hay `return` y se “cae” al bloque siguiente.
   - Si se llega sin haber devuelto issuer (cookie inválida/ausente o sesión “rota”): `if DEV_MODE and not is_api: return demo`; si no, `raise HTTPException(401, "No autorizado - redirigir a /login")`.
4. **Manejador global de excepciones** (`app.py`, ~153–158): para 401/403 en peticiones HTML (no `/api/`), responde con `RedirectResponse(url="/login")`.

Por tanto: la cookie se lee en el middleware y de nuevo en `get_portal_issuer`; ambos usan la misma cookie y `verify_session`. No hay ruta portal HTML que evite el middleware.

---

## 2. Caso exacto: ¿Con DEV_MODE=0, cookie inválida/expirada cae a demo?

**No.** Con `DEV_MODE=0` no existe en el código ningún camino donde una cookie inválida o expirada lleve al issuer demo.

- **Middleware:** `if session_data is None and not DEV_MODE` → con `DEV_MODE=0` redirige a `/login`; la petición no llega a `get_portal_issuer`.
- **get_portal_issuer:** Si por algún motivo la petición llegara sin sesión válida, `session_data` es `None`, no se entra en el bloque de sesión, y se evalúa `if DEV_MODE and not is_api`. Con `DEV_MODE=0` esa condición es falsa, no se devuelve demo, y se ejecuta `raise HTTPException(401, "No autorizado - redirigir a /login")`; el manejador global redirige a `/login`.

**Conclusión:** La caída al demo con cookie inválida/expirada ocurre **solo cuando `DEV_MODE` es verdadero** (por defecto `"1"` en `config.py` o `DEV_MODE=1` en entorno). En producción, si no se define `DEV_MODE=0`, el valor por defecto hace que parezca “a veces vuelve al demo” (p. ej. tras expiración de sesión o en despliegues donde no se exporta `DEV_MODE`).

---

## 3. COOKIE_SECURE y SameSite: por qué en HTTP local puede “perderse” la cookie si Secure=1

- **Comportamiento del atributo `Secure`:** Una cookie con `Secure=true` **solo se envía por HTTPS**. El navegador no la incluye en peticiones a `http://`.  
  Si en local usas `http://localhost` (o `http://127.0.0.1`) y la cookie se fija con `Secure=true` (por `COOKIE_SECURE=1` o porque el request tiene `x-forwarded-proto: https`), el servidor **sí** la escribe, pero en la **siguiente** petición por HTTP el navegador **no la envía**. El servidor recibe `request.cookies.get(SESSION_COOKIE_NAME) == None` → `verify_session(None)` → `None` → se trata como “sin sesión”. No es que la cookie se borre; es que no se envía.

- **Dónde se decide Secure:** `services/session.py`, `session_cookie_params(request)`: `secure = COOKIE_SECURE`; si `request` tiene `x-forwarded-proto: https` o `request.url.scheme == "https"`, se fuerza `secure = True`. En `config.py`, `COOKIE_SECURE` por defecto es `"1"` si `IS_PROD` (i.e. `ENV=prod`), y `"0"` en dev.

- **SameSite=Lax:** Se usa siempre. No hace que la cookie se “pierda” en HTTP; solo restringe en qué contextos se envía (p. ej. cross-site). En navegación normal (top-level) por HTTP o HTTPS la cookie se envía si no es `Secure` en HTTP.

**Resumen:** En entorno local **HTTP**, si por configuración o proxy la cookie se envía con `Secure=true`, el navegador no la incluye en las peticiones a `http://`, el servidor ve “sin cookie” y, según `DEV_MODE`, redirige a `/login` (DEV_MODE=0) o devuelve demo (DEV_MODE=1).

---

## 4. Causas posibles (prioridad)

### Alta

- **`DEV_MODE` por defecto `"1"`** (`config.py` línea 16). Si en producción no se define `DEV_MODE=0`, cookie inválida/expirada no provoca redirect a `/login` en el middleware y `get_portal_issuer` devuelve demo. Es la causa más probable de “a veces vuelve al demo”.

### Media

- **Sesión válida pero issuer o membresía inexistentes:** Cookie OK pero `get_issuer_by_id(issuer_id)` devuelve `None` (issuer borrado) o `get_membership(user_id, issuer_id)` devuelve `None`. En `get_portal_issuer` no hay `return` en esos casos y se cae al bloque `if DEV_MODE and not is_api: return demo`. Con `DEV_MODE=1` el usuario ve demo; con `DEV_MODE=0` se devuelve 401 y se redirige a `/login`.
- **Cookie no enviada (Secure sobre HTTP):** En prod, si alguna petición llega por HTTP, la cookie con `Secure=true` no se envía → mismo efecto que “cookie ausente” → con `DEV_MODE=1` demo.

### Baja

- **Variable de entorno no aplicada:** En el proceso/worker que sirve la petición no está definida `DEV_MODE=0` (p. ej. distintos workers o reinicio sin recargar env), por lo que se usa el default `"1"`.

---

## 5. Cómo reproducir (paso a paso)

### Escenario A: Cookie inválida → demo (comportamiento actual con default)

1. Asegurarse de que **no** está definido `DEV_MODE` en el entorno (o definir `DEV_MODE=1`).
2. Arrancar la app y abrir el portal (p. ej. `/portal/home`) con una sesión válida; cerrar el navegador o borrar la cookie `portal_session`.
3. Volver a abrir `/portal/home` (o recargar sin cookie).
4. **Resultado esperado (con default):** Se muestra el portal con issuer demo.  
   **Resultado esperado con `DEV_MODE=0`:** Redirect a `/login`.

### Escenario B: Cookie inválida → /login (comportamiento correcto en prod)

1. Definir `DEV_MODE=0` (y en prod `ENV=prod`).
2. Sin cookie (o con cookie expirada/inválida), ir a `/portal/home`.
3. **Resultado esperado:** Redirect 302 a `/login`.

### Escenario C: Sesión “rota” (issuer o membresía eliminados)

1. Con `DEV_MODE=1`, iniciar sesión y tener cookie válida con un `issuer_id`.
2. En la BD, borrar ese issuer o la membresía del usuario para ese issuer.
3. Recargar `/portal/home`.
4. **Resultado esperado con DEV_MODE=1:** Se muestra el demo.  
   **Resultado esperado con DEV_MODE=0:** 401 y redirect a `/login`.

### Escenario D: Cookie Secure en HTTP local

1. Forzar `COOKIE_SECURE=1` y acceder a la app por `http://...` (sin HTTPS).
2. Iniciar sesión (la cookie se fija con `Secure=true`).
3. Recargar la página o navegar de nuevo por `http://`.
4. **Resultado:** El navegador no envía la cookie → servidor ve sesión inválida → con `DEV_MODE=0` redirect a `/login`; con `DEV_MODE=1` demo.

---

## 6. Fix exacto recomendado (pequeño y seguro)

- **Objetivo:** Que en producción no se use el fallback a demo por defecto cuando la sesión es inválida o está rota.
- **Archivo:** `config.py`.
- **Qué tocar:** Asignación de la constante `DEV_MODE` (línea 16). No hay función; es carga de configuración al inicio del módulo.

**Cambio:**

```python
# Antes (línea 16):
DEV_MODE = os.getenv("DEV_MODE", "1") == "1"

# Después:
_DEV_MODE_DEFAULT = "0" if (os.getenv("ENV") or "").strip().lower() == "prod" else "1"
DEV_MODE = os.getenv("DEV_MODE", _DEV_MODE_DEFAULT) == "1"
```

**Efecto:** Con `ENV=prod` y sin `DEV_MODE` definido → `DEV_MODE = False`. Cookie inválida o sesión rota → redirect a `/login` (middleware o 401), no demo. En desarrollo (sin `ENV=prod`) se mantiene el default actual. No se añaden features; solo se cambia el default de `DEV_MODE` en prod.

---

## 7. Referencia rápida del flujo

| Condición | DEV_MODE=0 | DEV_MODE=1 (o default) |
|-----------|------------|--------------------------|
| Cookie ausente / inválida / expirada | Redirect `/login` | Demo |
| Cookie válida pero issuer no existe | 401 → `/login` | Demo |
| Cookie válida pero sin membresía | 401 → `/login` | Demo |
| Cookie no enviada (Secure sobre HTTP) | Redirect `/login` | Demo |

Con `DEV_MODE=0` no hay ningún camino en código que devuelva demo para cookie inválida o expirada.
