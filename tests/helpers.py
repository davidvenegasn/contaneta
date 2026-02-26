"""Helpers para tests (sesión, cookies)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def make_session_cookie(issuer_id: int, user_id: int = 0) -> dict[str, str]:
    """
    Devuelve un dict de cookies para usar con TestClient: { cookie_name: signed_value }.
    Requiere que config y services.session estén importables (SESSION_SECRET definido o aleatorio).
    """
    from services import session as session_service

    name = session_service.get_session_cookie_name()
    val = session_service.sign_session(user_id, issuer_id)
    return {name: val}
