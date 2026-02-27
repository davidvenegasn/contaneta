# Errores estandarizados del portal

Códigos HTTP y mensajes de usuario unificados para reducir confusión. No se cambian rutas.

## Helper

```python
from services.portal_errors import portal_error, portal_error_type

# Lanzar con código y mensaje explícitos (y opcional contexto de log)
portal_error(404, "El archivo no existe.", log_context={"issuer_id": 1, "path": "..."})

# Usar tipo predefinido (mapeo código + mensaje estándar)
portal_error_type("file_missing", log_context={"issuer_id": 1})
portal_error_type("parse_fail")
portal_error_type("reportlab_missing")
portal_error_type("php_missing")
# Mensaje personalizado manteniendo el código del tipo:
portal_error_type("server_error", override_message="No se pudo generar el PDF. Intenta de nuevo.")
```

## Tipos mapeados

| Tipo                | Código | Mensaje (resumen) |
|---------------------|--------|-------------------|
| `file_missing`      | 404    | El archivo no existe o ya no está disponible. |
| `file_invalid`      | 400    | El archivo no es válido. Revisa el formato. |
| `parse_fail`        | 500    | No se pudo leer el contenido. Intenta con otro archivo. |
| `php_missing`       | 503    | PHP no está disponible. Necesario para validación FIEL. |
| `reportlab_missing` | 503    | No se puede generar el PDF. Falta reportlab. |
| `pdfplumber_missing`| 503    | No se puede procesar el PDF. Falta pdfplumber. |
| `server_error`      | 500    | Ocurrió un error. Intenta de nuevo. |
| `not_found`         | 404    | El recurso no fue encontrado. |
| `unauthorized`      | 401    | Sesión inválida o expirada. |
| `forbidden`         | 403    | No tienes permiso para esta acción. |
| `bad_request`       | 400    | Revisa los datos e intenta de nuevo. |
| `rate_limited`      | 429    | Demasiados intentos. Espera un minuto. |

Textos completos en `services/portal_errors.MESSAGES`.

## Respuestas HTML (portal)

Cuando una ruta del portal (no `/api/`) lanza `HTTPException` y el cliente pide HTML (`Accept: text/html`), la app devuelve una página de error con:

- Título según código (No encontrado, Solicitud incorrecta, Error en el servidor, etc.)
- Código HTTP y mensaje (`detail`)
- CTAs: **Ir al inicio** (primario) y **Reintentar** (recarga)

Para peticiones `/api/*` se sigue devolviendo JSON con la estructura `{ ok, error: { code, message }, detail }`.
