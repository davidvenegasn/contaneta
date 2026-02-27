"""
Helpers de respuesta JSON (single source of truth para /api/*).

Meta:
- Respuestas consistentes para éxito y error (cuando el endpoint decide responder explícitamente).
- Los errores normalmente deben lanzarse (AppError / HTTPException) y los handlers globales se encargan.
"""

from __future__ import annotations

from typing import Any, Optional


def ok(data: Any = None, *, meta: Optional[dict[str, Any]] = None, **meta_kwargs: Any) -> dict:
    m = {}
    if isinstance(meta, dict):
        m.update(meta)
    m.update({k: v for k, v in meta_kwargs.items() if v is not None})
    out = {"ok": True}
    if data is not None:
        out["data"] = data
    if m:
        out["meta"] = m
    return out


def ok_list(items: list, total: int | None = None, *, meta: Optional[dict[str, Any]] = None, **meta_kwargs: Any) -> dict:
    """
    Para listados: mantener compatibilidad con el frontend actual que espera `items` en top-level.
    También incluye `data` con la misma info para contrato estable.
    """
    payload = {"items": items}
    if total is not None:
        payload["total"] = int(total)
    out = {"ok": True, **payload, "data": payload}
    m = {}
    if isinstance(meta, dict):
        m.update(meta)
    m.update({k: v for k, v in meta_kwargs.items() if v is not None})
    if m:
        out["meta"] = m
    return out


def fail(code: str, message: str, *, meta: Optional[dict[str, Any]] = None, **meta_kwargs: Any) -> dict:
    m = {}
    if isinstance(meta, dict):
        m.update(meta)
    m.update({k: v for k, v in meta_kwargs.items() if v is not None})
    out = {"ok": False, "error": {"code": code, "message": message}}
    if m:
        out["meta"] = m
    return out

