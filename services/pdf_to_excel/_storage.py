"""Storage path utilities for bank statement processing."""
import os


def get_storage_root(base_dir: str) -> str:
    """
    Root de storage. Respeta env APP_STORAGE_PATH si existe.
    - Si APP_STORAGE_PATH es relativo, se resuelve contra base_dir.
    - Siempre regresa ruta absoluta normalizada.
    """
    raw = (os.environ.get("APP_STORAGE_PATH") or "").strip()
    if raw:
        root = raw if os.path.isabs(raw) else os.path.join(base_dir, raw)
    else:
        root = os.path.join(base_dir, "storage")
    return os.path.normpath(os.path.abspath(root))


def safe_join(root_abs: str, *parts: str) -> str:
    """Une paths y asegura que queden bajo root_abs (previene path traversal)."""
    root_abs = os.path.normpath(os.path.abspath(root_abs))
    p = os.path.join(root_abs, *[str(x) for x in parts])
    abs_p = os.path.normpath(os.path.abspath(p))
    if abs_p == root_abs:
        return abs_p
    if not abs_p.startswith(root_abs + os.sep):
        raise ValueError("Ruta inválida (path traversal)")
    return abs_p


def ensure_parent_dir(path_abs: str) -> None:
    os.makedirs(os.path.dirname(path_abs), exist_ok=True)
