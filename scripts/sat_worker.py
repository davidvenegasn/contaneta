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
import time

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
from services.sat_autosync import update_sync_state_after_job  # noqa: E402
from services.catalog_from_cfdi import backfill_catalog_from_existing_cfdi  # noqa: E402

DB_PATH = os.environ.get("APP_DB_PATH") or os.path.join(BASE_DIR, "invoicing.db")
SAT_SYNC_DIR = os.path.join(BASE_DIR, "sat_sync")
PHP_SYNC = os.path.join(SAT_SYNC_DIR, "sync.php")
PHP_SYNC_XML = os.path.join(SAT_SYNC_DIR, "sync_xml.php")
PHP_VERIFY = os.path.join(SAT_SYNC_DIR, "verify_requests.php")
PHP_PARSE = os.path.join(SAT_SYNC_DIR, "parse_xml.php")
PHP_BIN = os.environ.get("PHP_BIN", "php")

# Backfill por defecto para sync.php (días)
SYNC_BACKFILL_DAYS = int(os.environ.get("SAT_SYNC_BACKFILL_DAYS", "7"))
SYNC_WINDOW_HOURS = int(os.environ.get("SAT_SYNC_WINDOW_HOURS", "6"))

# Full pipeline constants (onboarding / xml job_type)
ONBOARDING_BACKFILL_DAYS = int(os.environ.get("SAT_ONBOARDING_BACKFILL_DAYS", "60"))
VERIFY_MAX_ATTEMPTS = 10      # more attempts with shorter waits
VERIFY_WAIT_SECONDS = 30      # SAT typically needs 30-120s to prepare ZIPs


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


def run_sync_php(issuer_id: int, direction: str, *, reset: bool = False, loop: bool = True) -> tuple[bool, str]:
    """Ejecuta php sat_sync/sync.php <issuer_id> <issued|received>. Devuelve (éxito, mensaje)."""
    if not os.path.isfile(PHP_SYNC):
        return False, "No se encontró sat_sync/sync.php"
    env = os.environ.copy()
    env["APP_DB_PATH"] = DB_PATH
    args = [
        PHP_SYNC,
        str(issuer_id),
        direction,
        "--backfill=%d" % SYNC_BACKFILL_DAYS,
        "--window=%d" % min(SYNC_WINDOW_HOURS, 720),
    ]
    if loop:
        args.append("--loop")
    if reset:
        args.append("--reset")
    try:
        with decrypted_fiel_env(int(issuer_id)) as fiel_env:
            env.update(fiel_env)
            stdout, _stderr = run_php(
                args,
                cwd=SAT_SYNC_DIR,
                env=env,
                timeout=600,
                php_bin=PHP_BIN,
            )
        return True, (stdout or "").strip()[:500]
    except ExternalServiceError as e:
        msg = (e.internal_message or e.public_message or "Error desconocido").strip()[:500]
        return False, msg


def _run_php_step(label, args, env, timeout=300):
    """Run one PHP script. Returns (ok, message)."""
    try:
        stdout, _stderr = run_php(args, cwd=SAT_SYNC_DIR, env=env, timeout=timeout, php_bin=PHP_BIN)
        logger.info("[%s] %s", label, (stdout or "")[:300])
        return True, (stdout or "").strip()[:500]
    except ExternalServiceError as e:
        msg = (e.internal_message or e.public_message or "Error")[:500]
        logger.error("[%s] %s", label, msg)
        return False, msg


def _count_pending_requests(issuer_id):
    conn = db_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM sat_requests "
            "WHERE issuer_id=? AND status IN ('queued','verifying')",
            (issuer_id,),
        ).fetchone()
        return row["c"] if row else 0
    finally:
        conn.close()


def run_full_pipeline(issuer_id: int, direction: str) -> tuple[bool, str]:
    """Full SAT sync pipeline: metadata → request XMLs → verify/download → parse."""
    backfill = ONBOARDING_BACKFILL_DAYS
    env_base = os.environ.copy()
    env_base["APP_DB_PATH"] = DB_PATH

    try:
        with decrypted_fiel_env(int(issuer_id)) as fiel_env:
            env = {**env_base, **fiel_env}

            # Step 1: sync.php — metadata (--loop to process all windows)
            logger.info("Pipeline issuer=%s dir=%s: Step 1 — metadata (sync.php)", issuer_id, direction)
            ok, msg = _run_php_step("sync.php", [
                PHP_SYNC, str(issuer_id), direction,
                "--backfill=%d" % backfill,
                "--window=%d" % min(SYNC_WINDOW_HOURS, 720),
                "--loop",
            ], env, timeout=600)
            if not ok:
                return False, "Step 1 sync.php failed: %s" % msg

            # Step 2: sync_xml.php — request XML packages from SAT
            # --reset because sync.php just moved the checkpoint
            # --window=720 (30 days) = fewer SAT requests for 60-day backfill
            logger.info("Pipeline issuer=%s dir=%s: Step 2 — request XMLs (sync_xml.php)", issuer_id, direction)
            ok, msg = _run_php_step("sync_xml.php", [
                PHP_SYNC_XML, str(issuer_id), direction,
                "--backfill=%d" % backfill,
                "--window=720",
                "--reset",
                "--loop",
            ], env, timeout=600)
            if not ok:
                return False, "Step 2 sync_xml.php failed: %s" % msg

            # Step 3: verify_requests.php — poll SAT until packages are ready
            pending = _count_pending_requests(issuer_id)
            if pending > 0:
                logger.info("Pipeline issuer=%s dir=%s: Step 3 — verify %d pending requests", issuer_id, direction, pending)
                for attempt in range(1, VERIFY_MAX_ATTEMPTS + 1):
                    ok, msg = _run_php_step("verify_requests.php #%d" % attempt, [
                        PHP_VERIFY,
                        "--issuer=%d" % issuer_id,
                        "--direction=%s" % direction,
                    ], env, timeout=300)
                    # Check if there are still pending requests
                    remaining = _count_pending_requests(issuer_id)
                    if remaining == 0:
                        logger.info("Pipeline issuer=%s dir=%s: all requests verified", issuer_id, direction)
                        break
                    if attempt < VERIFY_MAX_ATTEMPTS:
                        logger.info("Pipeline issuer=%s dir=%s: %d requests still pending, waiting %ds (attempt %d/%d)",
                                    issuer_id, direction, remaining, VERIFY_WAIT_SECONDS, attempt, VERIFY_MAX_ATTEMPTS)
                        time.sleep(VERIFY_WAIT_SECONDS)
                else:
                    remaining = _count_pending_requests(issuer_id)
                    if remaining > 0:
                        logger.warning("Pipeline issuer=%s dir=%s: %d requests still pending after %d attempts",
                                       issuer_id, direction, remaining, VERIFY_MAX_ATTEMPTS)
            else:
                logger.info("Pipeline issuer=%s dir=%s: Step 3 — no pending requests, skipping verify", issuer_id, direction)

            # Step 4: parse_xml.php — extract totals, names, taxes from downloaded XMLs
            logger.info("Pipeline issuer=%s dir=%s: Step 4 — parse XMLs", issuer_id, direction)
            ok, msg = _run_php_step("parse_xml.php", [
                PHP_PARSE,
                "--issuer=%d" % issuer_id,
                "--direction=%s" % direction,
                "--limit=500",
            ], env, timeout=300)
            if not ok:
                return False, "Step 4 parse_xml.php failed: %s" % msg

    except ExternalServiceError as e:
        return False, (e.internal_message or e.public_message or "Pipeline error")[:500]
    except ValueError as e:
        return False, str(e)[:500]

    # Step 5: backfill client + product catalogs from parsed CFDIs (Python, no FIEL needed)
    if direction == "issued":
        try:
            logger.info("Pipeline issuer=%s dir=%s: Step 5 — backfill catalogs", issuer_id, direction)
            result = backfill_catalog_from_existing_cfdi(issuer_id)
            logger.info("Pipeline issuer=%s: catalogs updated — %d processed, %d clients, %d products",
                        issuer_id, result.processed, result.clients_upserted, result.observations_upserted)
        except Exception:
            logger.exception("Pipeline issuer=%s: catalog backfill failed (non-fatal)", issuer_id)

    logger.info("Pipeline issuer=%s dir=%s: completed successfully", issuer_id, direction)
    return True, "Pipeline completed"


def run_parse_only(issuer_id: int, direction: str) -> tuple[bool, str]:
    """Re-parse existing XMLs without downloading — for job_type='parse'."""
    env_base = os.environ.copy()
    env_base["APP_DB_PATH"] = DB_PATH

    try:
        with decrypted_fiel_env(int(issuer_id)) as fiel_env:
            env = {**env_base, **fiel_env}
            ok, msg = _run_php_step("parse_xml.php", [
                PHP_PARSE,
                "--issuer=%d" % issuer_id,
                "--direction=%s" % direction,
                "--limit=500",
            ], env, timeout=300)
            return ok, msg
    except ExternalServiceError as e:
        return False, (e.internal_message or e.public_message or "Parse error")[:500]
    except ValueError as e:
        return False, str(e)[:500]


def process_one_job(conn, job) -> bool:
    job_id = job["id"]
    issuer_id = job["issuer_id"]
    job_type = job["job_type"] or "metadata"
    direction = job["direction"] or "issued"
    if direction not in ("issued", "received"):
        mark_done(conn, job_id, False, "direction inválida")
        logger.error("Job %s: direction inválida", job_id)
        return True
    mark_running(conn, job_id)

    if job_type == "xml":
        logger.info("Job %s: full pipeline (xml) issuer=%s dir=%s", job_id, issuer_id, direction)
        ok, msg = run_full_pipeline(issuer_id, direction)
    elif job_type == "parse":
        logger.info("Job %s: parse only issuer=%s dir=%s", job_id, issuer_id, direction)
        ok, msg = run_parse_only(issuer_id, direction)
    else:
        # Default: metadata only (existing behavior)
        ok, msg = run_sync_php(issuer_id, direction)

    mark_done(conn, job_id, ok, None if ok else msg)
    # Update sat_sync_state for cooldown/status tracking
    try:
        update_sync_state_after_job(issuer_id, direction, ok=ok, error_msg=msg if not ok else None)
    except Exception:
        logger.exception("Failed to update sat_sync_state for issuer %s dir %s", issuer_id, direction)
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
