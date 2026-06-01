from __future__ import annotations

import hashlib
import json
import random
import sqlite3
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


def _stable_payload_json(payload: Any) -> str | None:
    if payload is None:
        return None
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        # Fallback: usar dumps normal (puede no ser estable pero evita reventar)
        return _json_dumps_or_none(payload)


def _payload_hash(*, issuer_id: int, name: str, payload_json: str | None) -> str:
    base = f"{int(issuer_id)}|{(name or '').strip()}|{(payload_json or '').strip()}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def enqueue_job(
    name: str,
    issuer_id: int,
    payload: dict | None = None,
    *,
    run_after: str | None = None,
    max_attempts: int = 3,
    priority: int = 0,
) -> int:
    """
    Encola un job con dedupe:
    - Si ya existe (issuer_id, name, payload_hash) en status queued/running, devuelve ese id.
    - Si no existe, crea uno nuevo.
    """
    if not name or not isinstance(name, str):
        raise ValueError("name requerido")
    issuer_id = int(issuer_id)
    name = name.strip()
    payload_json = _stable_payload_json(payload)
    p_hash = _payload_hash(issuer_id=issuer_id, name=name, payload_json=payload_json)
    max_attempts = int(max_attempts or 3)
    if max_attempts < 1:
        max_attempts = 1
    if max_attempts > 20:
        max_attempts = 20
    priority = int(priority or 0)

    conn = db()
    try:
        # Primero: intenta encontrar duplicado activo.
        row = fetch_one(
            conn,
            """
            SELECT id FROM jobs
            WHERE issuer_id = ? AND name = ? AND payload_hash = ?
              AND status IN ('queued','running')
            ORDER BY id ASC
            LIMIT 1
            """,
            (issuer_id, name, p_hash),
        )
        if row and row.get("id"):
            return int(row["id"])

        # Insert: si hay índice único parcial, puede lanzar IntegrityError -> devolvemos el existente.
        ra = (run_after or "").strip() or None
        try:
            cur = execute(
                conn,
                """
                INSERT INTO jobs (
                    issuer_id, name, status, progress, message,
                    payload_json, payload_hash,
                    attempts, max_attempts, run_after,
                    priority,
                    locked_by, locked_at,
                    result_json, error_json,
                    created_at, updated_at
                )
                VALUES (
                    ?, ?, 'queued', 0, NULL,
                    ?, ?,
                    0, ?, COALESCE(?, datetime('now')),
                    ?,
                    NULL, NULL,
                    NULL, NULL,
                    datetime('now'), datetime('now')
                )
                """,
                (issuer_id, name, payload_json, p_hash, max_attempts, ra, priority),
            )
            conn.commit()
            return int(cur.lastrowid)
        except sqlite3.IntegrityError:
            # Otro proceso insertó el duplicado.
            row2 = fetch_one(
                conn,
                """
                SELECT id FROM jobs
                WHERE issuer_id = ? AND name = ? AND payload_hash = ?
                  AND status IN ('queued','running')
                ORDER BY id ASC
                LIMIT 1
                """,
                (issuer_id, name, p_hash),
            )
            if row2 and row2.get("id"):
                return int(row2["id"])
            raise
    finally:
        conn.close()


def claim_next_job(worker_id: str, *, lease_seconds: int = 900) -> dict | None:
    """
    Claim atómico con BEGIN IMMEDIATE:
    - re-encola jobs running con lock vencido (lease)
    - toma el siguiente queued con run_after <= now
    """
    worker_id = (worker_id or "").strip() or "worker"
    lease_seconds = int(lease_seconds or 900)
    if lease_seconds < 30:
        lease_seconds = 30
    if lease_seconds > 3600 * 6:
        lease_seconds = 3600 * 6

    conn = db()
    try:
        execute(conn, "BEGIN IMMEDIATE")

        # Requeue stale running locks (worker murió).
        execute(
            conn,
            """
            UPDATE jobs
            SET status = 'queued',
                locked_by = NULL,
                locked_at = NULL,
                run_after = datetime('now'),
                updated_at = datetime('now'),
                message = COALESCE(message, 'requeued') || ' (lease vencido)'
            WHERE status = 'running'
              AND locked_at IS NOT NULL
              AND datetime(locked_at) <= datetime('now', ?)
            """,
            (f"-{lease_seconds} seconds",),
        )

        job = fetch_one(
            conn,
            """
            SELECT *
            FROM jobs
            WHERE status = 'queued'
              AND (run_after IS NULL OR datetime(run_after) <= datetime('now'))
            ORDER BY COALESCE(priority, 0) DESC, datetime(created_at) ASC, id ASC
            LIMIT 1
            """,
        )
        if not job:
            conn.commit()
            return None

        cur = execute(
            conn,
            """
            UPDATE jobs
            SET status = 'running',
                locked_by = ?,
                locked_at = datetime('now'),
                updated_at = datetime('now')
            WHERE id = ?
              AND status = 'queued'
              AND (run_after IS NULL OR datetime(run_after) <= datetime('now'))
            """,
            (worker_id, int(job["id"])),
        )
        if cur.rowcount != 1:
            conn.rollback()
            return None

        claimed = fetch_one(conn, "SELECT * FROM jobs WHERE id = ? LIMIT 1", (int(job["id"]),))
        conn.commit()
        if claimed:
            claimed["payload"] = _json_loads_or_none(claimed.get("payload_json"))
            claimed["result"] = _json_loads_or_none(claimed.get("result_json"))
            claimed["error"] = _json_loads_or_none(claimed.get("error_json"))
        return claimed
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def update_progress(job_id: int, *, progress: int | None = None, message: str | None = None) -> None:
    update_job(job_id, status=None, progress=progress, message=message)


def complete_job(job_id: int, result: dict | None = None) -> None:
    job_id = int(job_id)
    result_json = _json_dumps_or_none(result)
    conn = db()
    try:
        execute(
            conn,
            """
            UPDATE jobs
            SET status = 'success',
                progress = 100,
                result_json = ?,
                error_json = NULL,
                locked_by = NULL,
                locked_at = NULL,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (result_json, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def _next_backoff_seconds(attempts: int) -> int:
    # Exponencial con jitter, cap 10 minutos.
    base = min(600, max(2, int(2 ** max(0, attempts))))
    jitter = random.randint(0, min(10, base))
    return min(600, base + jitter)


def fail_job(
    job_id: int,
    *,
    error: dict | None = None,
    message: str | None = None,
    retry: bool = True,
) -> None:
    job_id = int(job_id)
    err_json = _json_dumps_or_none(error)
    msg = (message or "").strip() or None
    conn = db()
    try:
        execute(conn, "BEGIN IMMEDIATE")
        job = fetch_one(conn, "SELECT id, attempts, max_attempts FROM jobs WHERE id = ? LIMIT 1", (job_id,))
        if not job:
            conn.commit()
            return
        attempts_now = int(job.get("attempts") or 0)
        max_attempts = int(job.get("max_attempts") or 3)
        attempts_next = attempts_now + 1

        do_retry = bool(retry) and attempts_next < max_attempts
        if do_retry:
            delay = _next_backoff_seconds(attempts_next)
            execute(
                conn,
                """
                UPDATE jobs
                SET status = 'queued',
                    attempts = ?,
                    error_json = ?,
                    message = COALESCE(?, message),
                    locked_by = NULL,
                    locked_at = NULL,
                    run_after = datetime('now', ?),
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (attempts_next, err_json, msg, f"+{delay} seconds", job_id),
            )
        else:
            execute(
                conn,
                """
                UPDATE jobs
                SET status = 'failed',
                    attempts = ?,
                    error_json = ?,
                    message = COALESCE(?, message),
                    locked_by = NULL,
                    locked_at = NULL,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (attempts_next, err_json, msg, job_id),
            )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


# ---------------------------
# Compatibilidad (API legacy)
# ---------------------------


def run_job(name: str, issuer_id: int, payload: dict | None = None) -> int:
    """
    Crea un job genérico en estado queued.
    Nota: este módulo no ejecuta el trabajo; solo registra estado.
    """
    return enqueue_job(name, issuer_id, payload)


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
    if ok:
        complete_job(job_id, result)
    else:
        fail_job(job_id, error=result, message="Job failed", retry=False)


def get_job(job_id: int) -> dict | None:
    job_id = int(job_id)
    conn = db()
    try:
        row = fetch_one(conn, "SELECT * FROM jobs WHERE id = ? LIMIT 1", (job_id,))
        if not row:
            return None
        row["payload"] = _json_loads_or_none(row.get("payload_json"))
        row["result"] = _json_loads_or_none(row.get("result_json"))
        row["error"] = _json_loads_or_none(row.get("error_json"))
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
        row["error"] = _json_loads_or_none(row.get("error_json"))
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
            r["error"] = _json_loads_or_none(r.get("error_json"))
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

