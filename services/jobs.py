from __future__ import annotations

import json
from typing import Any

from database import db
from services.db_utils import execute, fetch_all, fetch_one, scalar


ALLOWED_STATUSES = {"queued", "running", "success", "failed"}


def _json_dumps_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _json_loads_or_none(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return value


def run_job(name: str, issuer_id: int, payload: dict | None = None) -> int:
    """
    Crea un job genérico en estado queued.
    Nota: este módulo no ejecuta el trabajo; solo registra estado.
    """
    if not name or not isinstance(name, str):
        raise ValueError("name requerido")
    issuer_id = int(issuer_id)
    payload_json = _json_dumps_or_none(payload)
    conn = db()
    try:
        cur = execute(
            conn,
            """
            INSERT INTO jobs (issuer_id, name, status, progress, message, payload_json, result_json, created_at, updated_at)
            VALUES (?, ?, 'queued', 0, NULL, ?, NULL, datetime('now'), datetime('now'))
            """,
            (issuer_id, name.strip(), payload_json),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def update_job(
    job_id: int,
    *,
    status: str | None = None,
    progress: int | None = None,
    message: str | None = None,
) -> None:
    job_id = int(job_id)
    sets: list[str] = []
    params: list[Any] = []

    if status is not None:
        status_norm = str(status).strip().lower()
        if status_norm not in ALLOWED_STATUSES:
            raise ValueError("status inválido")
        sets.append("status = ?")
        params.append(status_norm)

    if progress is not None:
        p = int(progress)
        if p < 0:
            p = 0
        if p > 100:
            p = 100
        sets.append("progress = ?")
        params.append(p)

    if message is not None:
        msg = str(message).strip()
        sets.append("message = ?")
        params.append(msg[:1000] if msg else None)

    if not sets:
        return

    sets.append("updated_at = datetime('now')")
    sql = f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?"
    params.append(job_id)

    conn = db()
    try:
        execute(conn, sql, tuple(params))
        conn.commit()
    finally:
        conn.close()


def finish_job(job_id: int, ok: bool, result: dict | None = None) -> None:
    status = "success" if ok else "failed"
    result_json = _json_dumps_or_none(result)
    job_id = int(job_id)
    conn = db()
    try:
        execute(
            conn,
            """
            UPDATE jobs
            SET status = ?, progress = 100, result_json = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (status, result_json, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_job(job_id: int) -> dict | None:
    job_id = int(job_id)
    conn = db()
    try:
        row = fetch_one(conn, "SELECT * FROM jobs WHERE id = ? LIMIT 1", (job_id,))
        if not row:
            return None
        row["payload"] = _json_loads_or_none(row.get("payload_json"))
        row["result"] = _json_loads_or_none(row.get("result_json"))
        return row
    finally:
        conn.close()


def get_job_for_issuer(job_id: int, issuer_id: int) -> dict | None:
    job_id = int(job_id)
    issuer_id = int(issuer_id)
    conn = db()
    try:
        row = fetch_one(
            conn,
            "SELECT * FROM jobs WHERE id = ? AND issuer_id = ? LIMIT 1",
            (job_id, issuer_id),
        )
        if not row:
            return None
        row["payload"] = _json_loads_or_none(row.get("payload_json"))
        row["result"] = _json_loads_or_none(row.get("result_json"))
        return row
    finally:
        conn.close()


def list_jobs(issuer_id: int, limit: int = 20) -> list[dict]:
    issuer_id = int(issuer_id)
    limit = int(limit)
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200
    conn = db()
    try:
        rows = fetch_all(
            conn,
            """
            SELECT *
            FROM jobs
            WHERE issuer_id = ?
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (issuer_id, limit),
        )
        for r in rows:
            r["payload"] = _json_loads_or_none(r.get("payload_json"))
            r["result"] = _json_loads_or_none(r.get("result_json"))
        return rows
    finally:
        conn.close()


def count_jobs(issuer_id: int) -> int:
    issuer_id = int(issuer_id)
    conn = db()
    try:
        n = scalar(conn, "SELECT COUNT(*) FROM jobs WHERE issuer_id = ?", (issuer_id,))
        return int(n or 0)
    finally:
        conn.close()

