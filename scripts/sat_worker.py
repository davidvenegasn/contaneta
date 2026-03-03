#!/usr/bin/env python3
"""
Worker para jobs SAT en cola (sat_jobs).
Toma jobs con status='queued', ejecuta sync.php para cada uno (issued/received)
y actualiza status a 'ok' o 'error' con last_error.
Idempotente: se puede ejecutar cada X minutos por cron.
Usa busy_timeout y WAL para evitar locks en SQLite.
"""
import logging
import os
import sys
import sqlite3

# Raíz del proyecto (donde está invoicing.db y sat_sync/)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("sat_worker")

from services.errors import ExternalServiceError  # noqa: E402
from services.subprocess_utils import run_php  # noqa: E402
from services.sat_credentials_secure import decrypted_fiel_env  # noqa: E402

DB_PATH = os.environ.get("APP_DB_PATH") or os.path.join(BASE_DIR, "invoicing.db")
SAT_SYNC_DIR = os.path.join(BASE_DIR, "sat_sync")
PHP_SYNC = os.path.join(SAT_SYNC_DIR, "sync.php")
PHP_BIN = os.environ.get("PHP_BIN", "php")

# Backfill por defecto para sync.php (días)
SYNC_BACKFILL_DAYS = int(os.environ.get("SAT_SYNC_BACKFILL_DAYS", "7"))
SYNC_WINDOW_HOURS = int(os.environ.get("SAT_SYNC_WINDOW_HOURS", "6"))


def db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def fetch_queued_jobs(conn):
    cur = conn.execute(
        """
        SELECT id, issuer_id, job_type, direction
        FROM sat_jobs
        WHERE status = 'queued'
        ORDER BY id ASC
        LIMIT 20
        """
    )
    return cur.fetchall()


def mark_running(conn, job_id):
    conn.execute(
        """
        UPDATE sat_jobs
        SET status = 'running', locked_at = datetime('now'), started_at = datetime('now'),
            attempts = attempts + 1, updated_at = datetime('now')
        WHERE id = ?
        """,
        (job_id,),
    )
    conn.commit()


def mark_done(conn, job_id, ok: bool, last_error: str = None):
    conn.execute(
        """
        UPDATE sat_jobs
        SET status = ?, finished_at = datetime('now'), last_error = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        ("ok" if ok else "error", last_error or None, job_id),
    )
    conn.commit()


def run_sync_php(issuer_id: int, direction: str) -> tuple[bool, str]:
    """Ejecuta php sat_sync/sync.php <issuer_id> <issued|received>. Devuelve (éxito, mensaje)."""
    if not os.path.isfile(PHP_SYNC):
        return False, "No se encontró sat_sync/sync.php"
    env = os.environ.copy()
    env["APP_DB_PATH"] = DB_PATH
    try:
        with decrypted_fiel_env(int(issuer_id)) as fiel_env:
            env.update(fiel_env)
            stdout, _stderr = run_php(
                [
                    PHP_SYNC,
                    str(issuer_id),
                    direction,
                    "--backfill=%d" % SYNC_BACKFILL_DAYS,
                    "--window=%d" % SYNC_WINDOW_HOURS,
                ],
                cwd=SAT_SYNC_DIR,
                env=env,
                timeout=600,
                php_bin=PHP_BIN,
            )
        return True, (stdout or "").strip()[:500]
    except ExternalServiceError as e:
        msg = (e.internal_message or e.public_message or "Error desconocido").strip()[:500]
        return False, msg


def process_one_job(conn, job) -> bool:
    job_id = job["id"]
    issuer_id = job["issuer_id"]
    direction = job["direction"] or "issued"
    if direction not in ("issued", "received"):
        mark_done(conn, job_id, False, "direction inválida")
        logger.error("Job %s: direction inválida", job_id)
        return True
    mark_running(conn, job_id)
    ok, msg = run_sync_php(issuer_id, direction)
    mark_done(conn, job_id, ok, None if ok else msg)
    if ok:
        logger.info("Job %s: ok", job_id)
    else:
        logger.error("Job %s: error: %s", job_id, msg or "desconocido")
    return True


def main():
    if not os.path.isfile(DB_PATH):
        logger.error("DB no encontrada: %s", DB_PATH)
        sys.exit(1)
    conn = db_connection()
    try:
        jobs = fetch_queued_jobs(conn)
        if not jobs:
            logger.info("0 jobs en cola. Nada que hacer.")
            return
        logger.info("%d job(s) en cola. Procesando...", len(jobs))
        for job in jobs:
            job_id = job["id"]
            issuer_id = job["issuer_id"]
            direction = job["direction"] or "issued"
            logger.info("Job %s: issuer_id=%s direction=%s", job_id, issuer_id, direction)
            process_one_job(conn, job)
        logger.info("Listo.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
