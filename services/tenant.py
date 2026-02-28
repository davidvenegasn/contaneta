from __future__ import annotations

from typing import Any


class TenantViolation(ValueError):
    pass


def require_issuer_id(issuer: dict[str, Any]) -> int:
    """
    Fuente única de issuer_id: SIEMPRE desde sesión/token (get_portal_issuer).
    Nunca del body/query.
    """
    try:
        issuer_id = int(issuer.get("id") or 0)
    except Exception as e:
        raise TenantViolation("issuer inválido") from e
    if issuer_id <= 0:
        raise TenantViolation("issuer inválido")
    return issuer_id

from __future__ import annotations

import re
from typing import Any, Mapping

from services.errors import ForbiddenError, NotFoundError


def _row_get(row: Any, key: str) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    if hasattr(row, "get"):
        try:
            return row.get(key)
        except Exception:
            pass
    if hasattr(row, "keys"):
        try:
            if key in row.keys():
                return row[key]
        except Exception:
            pass
    return None


def enforce_issuer(row: Any, issuer_id: int, *, issuer_key: str = "issuer_id") -> None:
    """
    Lanza ForbiddenError si `row[issuer_key]` no coincide con `issuer_id`.
    Si row es None, no hace nada (para usar junto con require_issuer_row).
    """
    if row is None:
        return
    rid = _row_get(row, issuer_key)
    if rid is None:
        # Si no hay issuer_id en el row, no podemos verificar: fallar cerrado.
        raise ForbiddenError(code="TENANT_ROW_NO_ISSUER", public_message="No tienes permiso para realizar esta acción.")
    if int(rid) != int(issuer_id):
        raise ForbiddenError(code="TENANT_FORBIDDEN", public_message="No tienes permiso para realizar esta acción.")


def require_issuer_row(
    row: Any,
    issuer_id: int,
    *,
    issuer_key: str = "issuer_id",
    not_found_public: str = "No encontrado.",
) -> Any:
    """
    Devuelve `row` si existe y pertenece al issuer.
    - Si no existe: NotFoundError
    - Si no coincide issuer: ForbiddenError (fail-closed)
    """
    if row is None:
        raise NotFoundError(public_message=not_found_public)
    enforce_issuer(row, issuer_id, issuer_key=issuer_key)
    return row


def ensure_issuer_filter(where_sql: str, *, issuer_col: str = "issuer_id") -> str:
    """
    Guardrail para builders SQL dinámicos.
    Si `where_sql` no contiene ya un filtro explícito por issuer_id, lo agrega:
      (where_sql) AND issuer_id = ?
    Si where_sql está vacío:
      issuer_id = ?
    """
    s = (where_sql or "").strip()
    if not s:
        return f"{issuer_col} = ?"
    if re.search(rf"\\b{re.escape(issuer_col)}\\b\\s*=", s):
        return s
    return f"({s}) AND {issuer_col} = ?"

