"""
Errores de aplicación (single source of truth).

Objetivo:
- 400 solo para errores del usuario (validación)
- 500/502 para fallos internos/externos
- Mensaje público consistente (sin stacktrace)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Any


@dataclass
class AppError(Exception):
    code: str
    public_message: str
    internal_message: Optional[str] = None
    status_code: int = 400
    meta: Optional[dict[str, Any]] = None

    def __post_init__(self) -> None:
        super().__init__(self.internal_message or self.public_message)


class ValidationError(AppError):
    def __init__(self, code: str = "VALIDATION_ERROR", public_message: str = "Revisa los datos e intenta de nuevo.", internal_message: str | None = None, *, meta: dict | None = None):
        super().__init__(code=code, public_message=public_message, internal_message=internal_message, status_code=400, meta=meta)


class NotFoundError(AppError):
    def __init__(self, code: str = "NOT_FOUND", public_message: str = "No encontrado.", internal_message: str | None = None, *, meta: dict | None = None):
        super().__init__(code=code, public_message=public_message, internal_message=internal_message, status_code=404, meta=meta)


class ForbiddenError(AppError):
    def __init__(self, code: str = "FORBIDDEN", public_message: str = "No tienes permiso para realizar esta acción.", internal_message: str | None = None, *, meta: dict | None = None):
        super().__init__(code=code, public_message=public_message, internal_message=internal_message, status_code=403, meta=meta)


class UnauthorizedError(AppError):
    def __init__(self, code: str = "UNAUTHORIZED", public_message: str = "Sesión inválida. Inicia sesión de nuevo.", internal_message: str | None = None, *, meta: dict | None = None):
        super().__init__(code=code, public_message=public_message, internal_message=internal_message, status_code=401, meta=meta)


class ExternalServiceError(AppError):
    def __init__(self, code: str = "EXTERNAL_SERVICE_ERROR", public_message: str = "No pudimos completar esta acción en este momento.", internal_message: str | None = None, *, meta: dict | None = None, status_code: int = 502):
        super().__init__(code=code, public_message=public_message, internal_message=internal_message, status_code=status_code, meta=meta)


class InternalError(AppError):
    def __init__(self, code: str = "INTERNAL_ERROR", public_message: str = "Ocurrió un error. Intenta de nuevo.", internal_message: str | None = None, *, meta: dict | None = None):
        super().__init__(code=code, public_message=public_message, internal_message=internal_message, status_code=500, meta=meta)

