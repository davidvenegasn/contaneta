"""Storage for declaration PDFs — tenant-scoped paths with SHA-256."""
import hashlib
import os
from pathlib import Path
from typing import Tuple


BASE_DIR = Path(os.getenv("DECLARATION_STORAGE_DIR", "./storage/declarations"))


def save_pdf_for_issuer(
    issuer_id: int, pdf_bytes: bytes, periodo_ym: str | None
) -> Tuple[str, str]:
    """Save PDF under storage/declarations/{issuer_id}/{YYYY-MM}/{sha256}.pdf

    Returns (relative_path, sha256_hex).
    """
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    subdir = BASE_DIR / str(issuer_id) / (periodo_ym or "unsorted")
    subdir.mkdir(parents=True, exist_ok=True)
    path = subdir / f"{sha[:16]}.pdf"
    if not path.exists():
        path.write_bytes(pdf_bytes)
    rel = str(path)
    return rel, sha
