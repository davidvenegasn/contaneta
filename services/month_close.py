from __future__ import annotations

import json
import os
import re
from typing import Any

from config import BASE_DIR
from database import db
from services.pdf_to_excel import get_storage_root, safe_join, ensure_parent_dir


_YM_RE = re.compile(r"^\d{4}-\d{2}$")


def _ym_ok(ym: str) -> str:
    s = (ym or "").strip()
    if not _YM_RE.match(s):
        raise ValueError("ym inválido (YYYY-MM)")
    return s


def _default_status() -> dict[str, Any]:
    return {"closed": False, "overrides": {}, "notes": ""}


def get_month_close_row(issuer_id: int, ym: str) -> dict | None:
    issuer_id = int(issuer_id)
    ym = _ym_ok(ym)
    conn = db()
    try:
        row = conn.execute(
            "SELECT issuer_id, ym, status_json, created_at, updated_at FROM month_close_status WHERE issuer_id = ? AND ym = ? LIMIT 1",
            (issuer_id, ym),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_status(issuer_id: int, ym: str) -> dict[str, Any]:
    row = get_month_close_row(int(issuer_id), ym)
    if not row or not row.get("status_json"):
        return _default_status()
    try:
        data = json.loads(row["status_json"] or "{}")
    except Exception:
        data = {}
    base = _default_status()
    if isinstance(data, dict):
        base.update({k: data.get(k) for k in base.keys()})
        if isinstance(data.get("overrides"), dict):
            base["overrides"] = data["overrides"]
    return base


def upsert_status(issuer_id: int, ym: str, status: dict[str, Any]) -> None:
    issuer_id = int(issuer_id)
    ym = _ym_ok(ym)
    payload = json.dumps(status or _default_status(), ensure_ascii=False)
    conn = db()
    try:
        conn.execute(
            """
            INSERT INTO month_close_status (issuer_id, ym, status_json, created_at, updated_at)
            VALUES (?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(issuer_id, ym) DO UPDATE SET
              status_json = excluded.status_json,
              updated_at = datetime('now')
            """,
            (issuer_id, ym, payload),
        )
        conn.commit()
    finally:
        conn.close()


def mark_closed(issuer_id: int, ym: str, closed: bool) -> None:
    st = get_status(int(issuer_id), ym)
    st["closed"] = bool(closed)
    upsert_status(int(issuer_id), ym, st)


def set_override(issuer_id: int, ym: str, key: str, value: Any) -> None:
    st = get_status(int(issuer_id), ym)
    ov = st.get("overrides") if isinstance(st.get("overrides"), dict) else {}
    ov[str(key)] = value
    st["overrides"] = ov
    upsert_status(int(issuer_id), ym, st)


def storage_paths(issuer_id: int, ym: str) -> dict[str, str]:
    """
    Paths relativos dentro de storage/ para acuse y opinión.
    Se guardan como:
      storage/month_close/{issuer_id}/{ym}/acuse.pdf
      storage/month_close/{issuer_id}/{ym}/opinion.pdf
    """
    issuer_id = int(issuer_id)
    ym = _ym_ok(ym)
    base = f"month_close/{issuer_id}/{ym}"
    return {
        "acuse_rel": f"{base}/acuse.pdf",
        "opinion_rel": f"{base}/opinion.pdf",
    }


def write_pdf_to_storage(*, issuer_id: int, ym: str, kind: str, pdf_bytes: bytes) -> str:
    issuer_id = int(issuer_id)
    ym = _ym_ok(ym)
    kind = (kind or "").strip().lower()
    if kind not in ("acuse", "opinion"):
        raise ValueError("kind inválido")
    paths = storage_paths(issuer_id, ym)
    rel = paths["acuse_rel"] if kind == "acuse" else paths["opinion_rel"]
    root = get_storage_root(BASE_DIR)
    abs_path = safe_join(root, rel)
    ensure_parent_dir(abs_path)
    with open(abs_path, "wb") as f:
        f.write(pdf_bytes)
    os.chmod(abs_path, 0o600)
    return rel


def get_pdf_abs_path(*, issuer_id: int, ym: str, kind: str) -> tuple[str, str]:
    """
    Devuelve (abs_path, rel_path). No valida existencia.
    """
    issuer_id = int(issuer_id)
    ym = _ym_ok(ym)
    kind = (kind or "").strip().lower()
    if kind not in ("acuse", "opinion"):
        raise ValueError("kind inválido")
    paths = storage_paths(issuer_id, ym)
    rel = paths["acuse_rel"] if kind == "acuse" else paths["opinion_rel"]
    root = get_storage_root(BASE_DIR)
    abs_path = safe_join(root, rel)
    return abs_path, rel


def pdf_exists(*, issuer_id: int, ym: str, kind: str) -> bool:
    abs_path, _rel = get_pdf_abs_path(issuer_id=int(issuer_id), ym=ym, kind=kind)
    return os.path.exists(abs_path)

