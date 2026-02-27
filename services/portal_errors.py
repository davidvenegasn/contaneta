"""
Errores estandarizados del portal: códigos HTTP, mensajes de usuario y contexto de log.
Sin cambiar rutas; mismo mensaje para el mismo tipo de error.
"""
import logging
from typing import Any, Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Mensajes estándar por tipo de error (evitar textos dispersos)
MESSAGES = {
    "file_missing": "El archivo no existe o ya no está disponible.",
    "file_invalid": "El archivo no es válido. Revisa el formato e intenta de nuevo.",
    "parse_fail": "No se pudo leer el contenido. Intenta con otro archivo o revisa que tenga el formato esperado.",
    "php_missing": "PHP no está disponible. Necesario para validación FIEL. Instala PHP en el servidor.",
    "reportlab_missing": "No se puede generar el PDF. Falta la dependencia reportlab. Instala: pip install reportlab",
    "pdfplumber_missing": "No se puede procesar el PDF. Falta la dependencia pdfplumber. Instala: pip install pdfplumber",
    "server_error": "Ocurrió un error. Intenta de nuevo.",
    "not_found": "El recurso no fue encontrado.",
    "unauthorized": "Sesión inválida o expirada.",
    "forbidden": "No tienes permiso para esta acción.",
    "bad_request": "Revisa los datos e intenta de nuevo.",
    "rate_limited": "Demasiados intentos. Espera un minuto e intenta de nuevo.",
}

# Mapeo tipo -> (status_code, user_message)
ERROR_MAP = {
    "file_missing": (404, MESSAGES["file_missing"]),
    "file_invalid": (400, MESSAGES["file_invalid"]),
    "parse_fail": (500, MESSAGES["parse_fail"]),
    "php_missing": (503, MESSAGES["php_missing"]),
    "reportlab_missing": (503, MESSAGES["reportlab_missing"]),
    "pdfplumber_missing": (503, MESSAGES["pdfplumber_missing"]),
    "server_error": (500, MESSAGES["server_error"]),
    "not_found": (404, MESSAGES["not_found"]),
    "unauthorized": (401, MESSAGES["unauthorized"]),
    "forbidden": (403, MESSAGES["forbidden"]),
    "bad_request": (400, MESSAGES["bad_request"]),
    "rate_limited": (429, MESSAGES["rate_limited"]),
}


def portal_error(
    code: int,
    user_message: str,
    log_context: Optional[dict[str, Any]] = None,
) -> None:
    """
    Lanza HTTPException con mensaje de usuario y opcionalmente registra contexto en log.
    Uso: portal_error(404, "El archivo no existe", {"issuer_id": 1, "path": "..."})
    Nunca retorna; siempre lanza.
    """
    if log_context:
        logger.warning(
            "portal_error: %s (code=%s) context=%s",
            user_message,
            code,
            log_context,
        )
    raise HTTPException(status_code=code, detail=user_message)


def portal_error_type(
    error_type: str,
    log_context: Optional[dict[str, Any]] = None,
    override_message: Optional[str] = None,
) -> None:
    """
    Lanza HTTPException usando el mapeo estándar (file_missing, parse_fail, php_missing, etc.).
    Si override_message se indica, se usa en lugar del mensaje por defecto del tipo.
    """
    if error_type not in ERROR_MAP:
        code, msg = 500, MESSAGES["server_error"]
    else:
        code, msg = ERROR_MAP[error_type]
    message = override_message if override_message is not None else msg
    portal_error(code, message, log_context=log_context)
