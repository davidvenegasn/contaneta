"""Log de acciones clave para SRE: una línea por acción con request_id (vía middleware)."""
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def log_action(request: Optional[Any], action: str, **kwargs: Any) -> None:
    """
    Escribe una línea de log con action= y pares key=value.
    El request_id se añade por el LogRecordFactory del app (middleware).
    Uso: log_action(request, "login", user_id=1, issuer_id=2)
    """
    parts = [f"action={action}"]
    for k, v in sorted(kwargs.items()):
        if v is not None and v != "":
            parts.append(f"{k}={v}")
    logger.info(" ".join(parts))
