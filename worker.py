from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from migrations_runner import apply_migrations
from services import jobs as jobs_service

logger = logging.getLogger(__name__)


@dataclass
class JobContext:
    job_id: int

    def progress(self, pct: int, message: str | None = None) -> None:
        jobs_service.update_progress(self.job_id, progress=pct, message=message)


JobHandler = Callable[[dict, JobContext], dict | None]


def _handler_not_implemented(job: dict, _ctx: JobContext) -> dict:
    raise RuntimeError(f"No hay handler para job.name={job.get('name')!r}")


def _load_handlers() -> dict[str, JobHandler]:
    """Handler registry.  Maps job name → handler function."""
    from services.sat_job_handlers import (
        handle_sat_sync_month,
        handle_sat_refresh_light,
        handle_sat_verify_credentials,
    )
    return {
        "sat_sync_month": handle_sat_sync_month,
        "sat_refresh_light": handle_sat_refresh_light,
        "sat_verify_credentials": handle_sat_verify_credentials,
    }


class _AlarmTimeout(Exception):
    pass


def _run_with_timeout(seconds: int, fn: Callable[[], Any]) -> Any:
    seconds = int(seconds or 0)
    if seconds <= 0:
        return fn()

    # Solo Unix. En Windows fallaría; este repo corre en Linux/macOS.
    def _alarm(_signum, _frame):
        raise _AlarmTimeout(f"Timeout {seconds}s")

    old = signal.signal(signal.SIGALRM, _alarm)
    try:
        signal.alarm(seconds)
        return fn()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def _run_once(*, worker_id: str, lease_seconds: int, job_timeout_seconds: int) -> bool:
    job = jobs_service.claim_next_job(worker_id, lease_seconds=lease_seconds)
    if not job:
        return False

    job_id = int(job["id"])
    ctx = JobContext(job_id=job_id)
    handlers = _load_handlers()
    handler = handlers.get((job.get("name") or "").strip(), _handler_not_implemented)

    def _do():
        ctx.progress(int(job.get("progress") or 0), "Ejecutando…")
        res = handler(job, ctx)
        return res or {"ok": True}

    try:
        result = _run_with_timeout(job_timeout_seconds, _do)
        jobs_service.complete_job(job_id, result=result if isinstance(result, dict) else {"ok": True, "result": str(result)})
    except _AlarmTimeout as e:
        jobs_service.fail_job(
            job_id,
            error={"type": "TIMEOUT", "message": str(e)},
            message="Timeout ejecutando job",
            retry=True,
        )
    except Exception as e:
        jobs_service.fail_job(
            job_id,
            error={"type": type(e).__name__, "message": str(e)},
            message="Error ejecutando job",
            retry=True,
        )
    return True


_SCHEDULER_INTERVAL_SECONDS = int(os.getenv("SAT_SCHEDULER_INTERVAL", "300"))  # 5 min
_last_schedule_run = 0.0


def _run_scheduler() -> None:
    """Enqueue sat_refresh_light jobs for eligible issuers whose cooldown expired."""
    global _last_schedule_run
    now = time.time()
    if now - _last_schedule_run < _SCHEDULER_INTERVAL_SECONDS:
        return
    _last_schedule_run = now

    from database import db as get_db

    conn = get_db()
    try:
        # Eligible issuers: valid FIEL, cooldown expired or no sync state yet
        rows = conn.execute(
            """
            SELECT DISTINCT sc.issuer_id
            FROM sat_credentials sc
            JOIN issuers i ON i.id = sc.issuer_id AND i.active = 1
            LEFT JOIN sat_sync_state ss
              ON ss.issuer_id = sc.issuer_id AND ss.direction = 'issued'
            WHERE sc.validation_ok = 1
              AND (ss.cooldown_until IS NULL OR ss.cooldown_until < datetime('now'))
            LIMIT 10
            """
        ).fetchall()
    finally:
        conn.close()

    for row in rows:
        issuer_id = row["issuer_id"] if isinstance(row, dict) else row[0]
        try:
            jobs_service.enqueue_job(
                "sat_refresh_light",
                issuer_id,
                payload={"issuer_id": issuer_id, "directions": ["issued", "received"]},
                max_attempts=2,
            )
            logger.info("Scheduled sat_refresh_light for issuer %s", issuer_id)
        except Exception:
            logger.exception("Failed to enqueue sat_refresh_light for issuer %s", issuer_id)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    argv = argv or sys.argv[1:]
    p = argparse.ArgumentParser(description="Worker simple para jobs (SQLite).")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="Reclama y ejecuta un solo job si existe.")
    mode.add_argument("--loop", action="store_true", help="Loop infinito: reclama y ejecuta jobs.")
    p.add_argument("--sleep", type=float, default=1.0, help="Sleep entre iteraciones cuando no hay jobs (loop).")
    p.add_argument("--worker-id", default=os.getenv("WORKER_ID") or "worker-1", help="ID del worker para locks.")
    p.add_argument("--lease-seconds", type=int, default=int(os.getenv("JOB_LEASE_SECONDS") or "900"))
    p.add_argument("--timeout-seconds", type=int, default=int(os.getenv("JOB_TIMEOUT_SECONDS") or "60"))
    p.add_argument("--db", default=os.getenv("APP_DB_PATH") or os.getenv("DB_PATH") or "", help="Opcional: path DB (solo para migraciones).")
    p.add_argument("--no-scheduler", action="store_true", help="Disable auto-sync scheduler in loop mode.")
    args = p.parse_args(argv)

    # Asegurar migraciones antes de trabajar (incluye 025 jobs_robust).
    if args.db:
        apply_migrations(args.db)

    if args.once:
        ran = _run_once(worker_id=args.worker_id, lease_seconds=args.lease_seconds, job_timeout_seconds=args.timeout_seconds)
        return 0 if ran else 1

    # loop
    while True:
        ran = _run_once(worker_id=args.worker_id, lease_seconds=args.lease_seconds, job_timeout_seconds=args.timeout_seconds)
        if not args.no_scheduler:
            try:
                _run_scheduler()
            except Exception:
                logger.exception("Scheduler error")
        if not ran:
            time.sleep(max(0.2, float(args.sleep)))


if __name__ == "__main__":
    raise SystemExit(main())

