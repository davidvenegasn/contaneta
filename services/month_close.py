from __future__ import annotations

import json
import os
import re
from typing import Any

from config import BASE_DIR
from database import db
from services.pdf_to_excel import ensure_parent_dir, get_storage_root, safe_join

_YM_RE = re.compile(r"^\d{4}-\d{2}$")


def _ym_ok(ym: str) -> str:
    s = (ym or "").strip()
    if not _YM_RE.match(s):
        raise ValueError("ym inválido (YYYY-MM)")
    return s


VALID_STATUSES = ("draft", "submitted", "confirmed")

DEFAULT_CHECKLIST = {
    "sat_sync": False,
    "issued_ok": False,
    "received_ok": False,
    "bank_ok": False,
    "reconciliation_ok": False,
    "tax_estimate_ok": False,
    "acuse_uploaded": False,
    "opinion_uploaded": False,
}


def _default_status() -> dict[str, Any]:
    return {"closed": False, "overrides": {}, "notes": ""}


def get_month_close_row(issuer_id: int, ym: str) -> dict | None:
    issuer_id = int(issuer_id)
    ym = _ym_ok(ym)
    conn = db()
    try:
        row = conn.execute(
            """SELECT issuer_id, ym, status_json, status, checklist_json,
                      acuse_pdf_path, opinion_pdf_path, created_at, updated_at
               FROM month_close_status WHERE issuer_id = ? AND ym = ? LIMIT 1""",
            (issuer_id, ym),
        ).fetchone()
        return dict(row) if row else None
    except Exception:
        # Fallback if new columns don't exist yet
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


# ---------- Enhanced API (JOB 1) ----------

def get_checklist(issuer_id: int, ym: str) -> dict[str, bool]:
    """Get the checklist for a month. Returns merged defaults + saved."""
    row = get_month_close_row(int(issuer_id), ym)
    base = dict(DEFAULT_CHECKLIST)
    if row and row.get("checklist_json"):
        try:
            saved = json.loads(row["checklist_json"])
            if isinstance(saved, dict):
                for k in base:
                    if k in saved:
                        base[k] = bool(saved[k])
        except Exception:
            pass
    # Auto-detect acuse/opinion from storage
    base["acuse_uploaded"] = pdf_exists(issuer_id=int(issuer_id), ym=ym, kind="acuse")
    base["opinion_uploaded"] = pdf_exists(issuer_id=int(issuer_id), ym=ym, kind="opinion")
    return base


def get_month_status_enum(issuer_id: int, ym: str) -> str:
    """Get the status enum (draft/submitted/confirmed)."""
    row = get_month_close_row(int(issuer_id), ym)
    if row and row.get("status") in VALID_STATUSES:
        return row["status"]
    return "draft"


def save_month_close(
    issuer_id: int,
    ym: str,
    *,
    status: str | None = None,
    checklist: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Save month close data (status + checklist). Returns the saved row."""
    issuer_id = int(issuer_id)
    ym = _ym_ok(ym)

    # Validate status
    status_val = (status or "").strip().lower() if status else None
    if status_val and status_val not in VALID_STATUSES:
        raise ValueError(f"status inválido: {status_val}")

    # Get existing or defaults
    existing_status = get_status(issuer_id, ym)
    existing_checklist = get_checklist(issuer_id, ym)

    if checklist and isinstance(checklist, dict):
        for k, v in checklist.items():
            if k in existing_checklist:
                existing_checklist[k] = bool(v)

    checklist_json = json.dumps(existing_checklist, ensure_ascii=False)
    status_json = json.dumps(existing_status, ensure_ascii=False)
    new_status = status_val or get_month_status_enum(issuer_id, ym)

    # Get PDF paths
    has_acuse = pdf_exists(issuer_id=issuer_id, ym=ym, kind="acuse")
    has_opinion = pdf_exists(issuer_id=issuer_id, ym=ym, kind="opinion")
    paths = storage_paths(issuer_id, ym)
    acuse_path = paths["acuse_rel"] if has_acuse else None
    opinion_path = paths["opinion_rel"] if has_opinion else None

    conn = db()
    try:
        conn.execute(
            """
            INSERT INTO month_close_status (issuer_id, ym, status_json, status, checklist_json,
                                            acuse_pdf_path, opinion_pdf_path, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(issuer_id, ym) DO UPDATE SET
              status_json = excluded.status_json,
              status = excluded.status,
              checklist_json = excluded.checklist_json,
              acuse_pdf_path = excluded.acuse_pdf_path,
              opinion_pdf_path = excluded.opinion_pdf_path,
              updated_at = datetime('now')
            """,
            (issuer_id, ym, status_json, new_status, checklist_json,
             acuse_path, opinion_path),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "issuer_id": issuer_id,
        "ym": ym,
        "status": new_status,
        "checklist": existing_checklist,
        "acuse_pdf_path": acuse_path,
        "opinion_pdf_path": opinion_path,
    }


def get_full_month_close(issuer_id: int, ym: str) -> dict[str, Any]:
    """Get full month close data for API response."""
    issuer_id = int(issuer_id)
    ym = _ym_ok(ym)
    return {
        "issuer_id": issuer_id,
        "ym": ym,
        "status": get_month_status_enum(issuer_id, ym),
        "checklist": get_checklist(issuer_id, ym),
        "status_detail": get_status(issuer_id, ym),
        "acuse_uploaded": pdf_exists(issuer_id=issuer_id, ym=ym, kind="acuse"),
        "opinion_uploaded": pdf_exists(issuer_id=issuer_id, ym=ym, kind="opinion"),
    }

