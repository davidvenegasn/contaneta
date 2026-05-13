"""Static asset versioning for cache-busting.

Provides a ``static_url`` helper that appends a content-based hash query
parameter (``?v=<hash>``) to static file paths. The hash is computed from
the file contents the first time the file is requested, then cached
in-memory for the lifetime of the process.
"""

import hashlib
import logging
import os

from config import STATIC_DIR

logger = logging.getLogger(__name__)

# In-memory cache: relative_path -> short content hash
_hash_cache: dict[str, str] = {}


def _file_hash(filepath: str) -> str:
    """Compute a short SHA-256 hex digest of the file contents.

    Args:
        filepath: Absolute path to the file.

    Returns:
        First 8 characters of the SHA-256 hex digest.
    """
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:8]


def static_url(path: str) -> str:
    """Return a versioned URL for a static asset.

    Appends ``?v=<content_hash>`` so browsers cache-bust on content change.
    Falls back to the plain ``/static/<path>`` URL if the file does not exist.

    Args:
        path: Relative path within the static directory (e.g. ``css/portal.css``).

    Returns:
        URL string like ``/static/css/portal.css?v=a1b2c3d4``.
    """
    # Normalise: strip leading slash or /static/ prefix for consistency
    clean = path.lstrip("/")
    if clean.startswith("static/"):
        clean = clean[len("static/"):]

    base_url = f"/static/{clean}"

    if clean in _hash_cache:
        return f"{base_url}?v={_hash_cache[clean]}"

    filepath = os.path.join(STATIC_DIR, clean)
    if not os.path.isfile(filepath):
        logger.debug("static_url: file not found %s", filepath)
        return base_url

    try:
        content_hash = _file_hash(filepath)
        _hash_cache[clean] = content_hash
        return f"{base_url}?v={content_hash}"
    except Exception:
        logger.warning("static_url: could not hash %s", filepath, exc_info=True)
        return base_url


def clear_cache() -> None:
    """Clear the in-memory hash cache (e.g. during development reload)."""
    _hash_cache.clear()
