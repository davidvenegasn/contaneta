# Spec: Errores 500 y manejo de excepciones en el portal

**ID:** `SPEC-01`  
**Origen:** AUDIT_README.md — Estabilidad, Job 1  
**Prioridad:** Alta

---

## Objetivo

Evitar que errores de servidor (BD, subprocess, archivos, excepciones no controladas) se devuelvan como 400 con el mensaje crudo de la excepción. Unificar: fallos de servidor → 500 con mensaje genérico y logging adecuado.

---

## Alcance

- Rutas en `routers/portal.py` que sirven HTML y usan `try/except Exception` devolviendo `HTMLResponse(..., status_code=400)` o JSON con `str(e)`.
- Cualquier ruta del portal que capture excepciones y responda con 400 cuando el fallo es del servidor (BD, subprocess, FileNotFoundError, etc.).
- Asegurar que el handler global de 500 en `app.py` siga devolviendo mensaje genérico (sin stack ni rutas internas) al cliente.

---

## Fuera de alcance

- Cambiar la lógica de validación de entrada (errores de cliente siguen siendo 400 con mensaje de validación).
- Añadir timeouts a subprocess (spec 02 / otra spec).
- Cambios en `routers/api.py` o `routers/admin.py` salvo si también devuelven 400 con cuerpo de excepción en flujos equivalentes.
- Modificar el contenido del mensaje que ve el usuario en 500 (solo asegurar que sea genérico y no el texto de la excepción).

---

## Archivos a tocar

| Archivo / directorio | Cambio previsto |
|----------------------|-----------------|
| `routers/portal.py` | Revisar todos los `try/except` que devuelven 400; reemplazar por `HTTPException(500, detail="...")` o dejar que la excepción suba al handler global. Añadir `logging.exception` o `logging.error` antes de re-lanzar si se captura. |
| `app.py` | Verificar que el handler 500 no exponga stack/detalle interno (solo mensaje genérico). Opcional: documentar en comentario. |

---

## Reglas

1. Si el fallo es por datos del cliente (ej. archivo no PDF, parámetro inválido), seguir devolviendo 400 con mensaje claro.
2. Si el fallo es de servidor (BD, subprocess, archivo no encontrado en disco, excepción inesperada), devolver 500. No poner `str(e)` ni el tipo de excepción en el cuerpo de la respuesta al cliente.
3. Al capturar para devolver 500, hacer `logging.exception(...)` o `logging.error(...)` con contexto (ruta, issuer_id si aplique) antes de lanzar `HTTPException(500, detail="Ha ocurrido un error. Intenta de nuevo.")` o similar.
4. Opcional: si se quiere dar un mensaje más específico pero seguro (ej. "No se pudo procesar el archivo"), que no incluya rutas de disco ni detalles técnicos.

---

## Criterios de aceptación

- [ ] Ninguna ruta del portal devuelve 400 con el cuerpo de una excepción de servidor (BD, subprocess, IO, etc.).
- [ ] Los fallos de servidor en rutas del portal devuelven 500 con un mensaje genérico (o el mensaje definido en el handler global).
- [ ] En logs queda registrado el error real (logging.exception o logging.error) para diagnóstico.
- [ ] El handler global de 500 en `app.py` no expone stack trace ni rutas internas en la respuesta al cliente.
- [ ] Las respuestas JSON a peticiones que pidan JSON (Accept: application/json) en rutas afectadas devuelven `{ "detail": "..." }` con status 500.

---

## Cómo probarlo manualmente

1. **Simular error de BD:** En una ruta del portal que use `db()`, provocar un fallo (ej. DB bloqueada o ruta inexistente). Verificar que la respuesta sea 500 y que el cuerpo no contenga el mensaje crudo de sqlite3.
2. **Simular error en subprocess/archivo:** En una ruta que use PHP o lea archivos (SAT, bank PDF), provocar que falle (ej. archivo no encontrado). Verificar 500 y mensaje genérico.
3. **Validación de cliente:** Enviar un request inválido (ej. archivo que no sea PDF). Verificar que siga siendo 400 con mensaje de validación.
4. **Logs:** Reproducir un 500 y comprobar que en los logs del servidor aparezca la excepción real para soporte.
5. **API/JSON:** Hacer una petición con `Accept: application/json` a una ruta que pueda fallar; verificar que el 500 devuelva JSON con `detail` y no HTML.

---

## Referencias

- AUDIT_README.md — Sección 1 (Estabilidad), Lista priorizada Alta, Job 1.
- app.py — `server_error_handler`, `_html_error`, `_api_error_body`.
