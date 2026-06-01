"""Atomic full-sync pipeline: metadata -> XML request -> verify/download -> parse.

Runs all 4 phases in a single job to prevent checkpoint interference between
sync.php (metadata) and sync_xml.php (XML download). Includes smart retry
when SAT returns 'Sin informacion' but metadata indicates CFDIs exist.
"""
from __future__ import annotations

import logging
import time

from services.sat.sat_job_handlers import (
    _run_sync_php,
    _run_xml_pipeline,
    _update_sync_state,
)
from services.sat.sat_metadata_only_repair import (
    count_metadata_only,
    reset_checkpoint_for_repair,
)

logger = logging.getLogger(__name__)


def handle_sat_full_sync(job: dict, ctx) -> dict:
    """Atomic pipeline: metadata -> request XMLs -> verify/download -> parse.

    Smart retries: if SAT returns 'Sin informacion' but metadata sync
    reported CFDIs in the window, wait and retry up to 3 times.

    Payload: {issuer_id, direction, backfill_days?, window_hours?}
    """
    payload = job.get("payload") or {}
    issuer_id = int(payload.get("issuer_id") or job.get("issuer_id"))
    direction = payload.get("direction", "issued")
    backfill_days = int(payload.get("backfill_days", 180))
    window_hours = int(payload.get("window_hours", 168))

    results = {
        "metadata_synced": False,
        "xml_pipeline_ok": False,
        "retries": 0,
        "errors": [],
    }

    # Phase 1: Metadata sync
    ctx.progress(10, f"Phase 1: metadata sync {direction}")
    ok, msg = _run_sync_php(issuer_id, direction, backfill_days=backfill_days, window_hours=window_hours)
    results["metadata_synced"] = ok

    if not ok:
        _update_sync_state(issuer_id, direction, ok=False, error_msg=msg)
        results["errors"].append(f"metadata: {msg}")
        raise RuntimeError(f"SAT metadata sync failed: {msg}")

    # Check how many metadata-only remain after metadata sync
    pre_counts = count_metadata_only(issuer_id)
    has_metadata_only = (
        pre_counts.get(f"{direction}_metadata_only", 0) > 0
    )

    # Phase 2: Reset checkpoint if metadata brought new data, then XML pipeline
    if has_metadata_only:
        from datetime import datetime, timedelta, timezone
        from_date = (datetime.now(timezone.utc) - timedelta(days=backfill_days)).strftime("%Y-%m-%d %H:%M:%S")
        reset_checkpoint_for_repair(issuer_id, from_date)

    # Phase 3-4: XML request + verify/download + parse, with smart retry
    max_retries = 3
    retry_delay = 60  # 1 minute between retries (configurable via env)
    for attempt in range(max_retries + 1):
        ctx.progress(40 + attempt * 15, f"Phase 2-4: XML pipeline (attempt {attempt + 1})")
        xml_ok, xml_msg = _run_xml_pipeline(
            issuer_id, direction,
            backfill_days=backfill_days,
            window_hours=window_hours,
        )
        results["xml_pipeline_ok"] = xml_ok

        if xml_ok:
            break

        # Check if SAT said "Sin informacion" but we know there are metadata-only CFDIs
        post_counts = count_metadata_only(issuer_id)
        still_missing = post_counts.get(f"{direction}_metadata_only", 0)

        if still_missing > 0 and attempt < max_retries:
            results["retries"] = attempt + 1
            logger.info(
                "SAT returned no info but %d CFDIs still metadata-only for issuer=%s/%s, retry %d/%d",
                still_missing, issuer_id, direction, attempt + 1, max_retries,
            )
            time.sleep(retry_delay)
        else:
            if not xml_ok:
                results["errors"].append(f"xml_pipeline: {xml_msg}")
            break

    # Update sync state
    _update_sync_state(issuer_id, direction, ok=True)
    ctx.progress(100, "Done")

    return {"ok": True, **results}


def enqueue_sat_full_sync(
    issuer_id: int,
    direction: str = "issued",
    backfill_days: int = 180,
) -> int | None:
    """Enqueue a sat_full_sync job via the generic job queue."""
    from services.jobs import enqueue_job
    return enqueue_job(
        "sat_full_sync",
        issuer_id,
        payload={
            "issuer_id": issuer_id,
            "direction": direction,
            "backfill_days": backfill_days,
        },
        max_attempts=2,
    )
