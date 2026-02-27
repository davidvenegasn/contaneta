# Cómo probar el registro y login (paso a paso)

Sigue estos pasos en orden.

---

## Paso 1: Abrir la terminal

Abre la terminal (en Mac: Terminal o la terminal integrada de Cursor) y deja el “cursor” en la carpeta del proyecto.

Si no estás en la carpeta del proyecto, escribe:

```bash
cd /Users/macbokpro/Documents/Projects/conta_invoicing_mvp_PRO_clean
```

(y Enter).

---

## Paso 2: Activar el entorno virtual (si lo usas)

Si tienes una carpeta `.venv` o `venv` en el proyecto, actívala:

```bash
source .venv/bin/activate
```

(Si no tienes venv, ignora este paso.)

---

## Paso 3: Instalar dependencias

En la misma terminal:

```bash
pip install -r requirements.txt
```

Espera a que termine. Así se instalan FastAPI, passlib (contraseñas), httpx (para Google/Facebook), etc.

---

## Paso 4: Aplicar las migraciones de la base de datos

En la misma terminal:

```bash
python3 -c "from migrations_runner import apply_migrations; apply_migrations('invoicing.db'); print('Listo')"
```

Si ves `Listo`, la base de datos ya tiene las tablas `users` y `memberships`.

---

## Paso 5: Levantar el servidor

En la misma terminal:

```bash
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

Deja esa terminal abierta. Cuando veas algo como:

```
Uvicorn running on http://127.0.0.1:8000
```

el servidor está corriendo.

---

## Paso 6: Abrir el navegador

Abre Chrome, Safari o el navegador que uses y ve a:

**http://127.0.0.1:8000/signup**

Deberías ver la página **“Crear cuenta”** con:

- Opción Correo / Teléfono  
- Campos de contraseña  
- Checkboxes de términos y autorización al despacho  
- Botones de Google y Facebook  

---

## Paso 7: Registrarte con correo

1. Deja seleccionado **“Correo”**.
2. Escribe un correo que recuerdes (ej. `prueba@ejemplo.com`).
3. Escribe una contraseña (mínimo 8 caracteres) y repítela en “Confirmar contraseña”.
4. Marca el checkbox **“Acepto los Términos y condiciones y el Aviso de privacidad”**.
5. (Opcional) Marca **“Autorizo a V&G Fiscal…”** si quieres probar el acceso del despacho.
6. Pulsa **“Crear cuenta”**.

Deberías ir a la página **“Completa tu perfil fiscal”** (onboarding).

---

## Paso 8: Completar el perfil fiscal (onboarding)

1. Escribe un **RFC** (puede ser de prueba, ej. `XAXX010101000`).
2. Escribe **Razón social** (ej. “Mi empresa prueba”).
3. Elige **Régimen fiscal** (puedes dejar “616 - Sin obligaciones fiscales”).
4. Pulsa **“Continuar al portal”**.

Deberías entrar al **portal** (pantalla principal del sistema).

---

## Paso 9: Cerrar sesión y probar el login

1. En el portal, busca la opción de **Cerrar sesión** (o abre en el navegador: **http://127.0.0.1:8000/logout**).
2. Luego abre: **http://127.0.0.1:8000/login**
3. Elige **“Correo”**, escribe el mismo correo y contraseña que usaste en el registro.
4. Pulsa **“Entrar”**.

Deberías volver a entrar al portal.

---

## Resumen rápido

| Qué quieres hacer      | Dónde ir                          |
|------------------------|------------------------------------|
| Crear cuenta nueva     | http://127.0.0.1:8000/signup       |
| Entrar con correo/tel  | http://127.0.0.1:8000/login        |
| Ver términos           | http://127.0.0.1:8000/terms        |
| Ver aviso de privacidad| http://127.0.0.1:8000/privacy      |
| Cerrar sesión          | http://127.0.0.1:8000/logout       |

---

## Si algo falla

- **“ModuleNotFoundError”**  
  Vuelve a hacer el Paso 3 (`pip install -r requirements.txt`) y asegúrate de estar en el mismo entorno (venv si lo usas).

- **“Token inválido” o no entra al portal**  
  Revisa que hayas completado registro (Paso 7) y luego onboarding (Paso 8). Si entras por **login** con correo/contraseña, no uses el token; el token es solo para el enlace antiguo tipo `/login?token=XXX`.

- **El servidor no arranca**  
  Comprueba que nadie más esté usando el puerto 8000. Puedes probar otro puerto:  
  `uvicorn app:app --reload --host 127.0.0.1 --port 8001`  
  y entonces abrir **http://127.0.0.1:8001/signup**.
