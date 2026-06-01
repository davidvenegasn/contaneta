"""Admin SAT repair and diagnostic routes."""
import logging

from fastapi import Body, Depends, HTTPException
from fastapi.responses import JSONResponse

from routers.admin._deps import require_admin
from services import audit
from services.sat.sat_metadata_only_repair import (
    count_metadata_only,
    find_metadata_only_cfdis,
    reset_checkpoint_for_repair,
)

logger = logging.getLogger(__name__)


def register_sat_admin_routes(router, templates):
    """Register admin SAT diagnostic and repair routes."""

    @router.post("/sat/repair-metadata-only")
    def admin_repair_metadata_only(
        body: dict = Body(...),
        _admin: tuple[int, int, int | None] = Depends(require_admin),
    ):
        """Detect and trigger repair for metadata-only CFDIs.

        Accepts {issuer_id: int, backfill_days: int (optional, default 180)}.
        Resets checkpoint and enqueues a background job for XML re-sync.
        """
        user_id, _, _ = _admin
        target_issuer_id = body.get("issuer_id")
        if not target_issuer_id:
            raise HTTPException(status_code=400, detail="issuer_id requerido")
        target_issuer_id = int(target_issuer_id)
        backfill_days = int(body.get("backfill_days", 180))

        # Count current state
        counts = count_metadata_only(target_issuer_id)
        metadata_only_total = counts["issued_metadata_only"] + counts["received_metadata_only"]

        if metadata_only_total == 0:
            return JSONResponse({"ok": True, "message": "No hay CFDIs metadata-only", "counts": counts})

        # Reset checkpoint to force re-sync
        from datetime import datetime, timedelta, timezone
        from_date = (datetime.now(timezone.utc) - timedelta(days=backfill_days)).strftime("%Y-%m-%d %H:%M:%S")
        reset_checkpoint_for_repair(target_issuer_id, from_date)

        # Enqueue background job if generic jobs table exists
        job_id = None
        try:
            from services.jobs import enqueue_job
            job_id = enqueue_job(
                "sat_xml_backfill",
                target_issuer_id,
                payload={"issuer_id": target_issuer_id, "backfill_days": backfill_days},
            )
        except Exception:
            logger.debug("Could not enqueue job, jobs table may not exist", exc_info=True)

        audit.log(
            action="admin_sat_repair",
            user_id=user_id,
            issuer_id=target_issuer_id,
            details=f"metadata_only={metadata_only_total} backfill_days={backfill_days} job_id={job_id}",
        )

        return JSONResponse({
            "ok": True,
            "message": f"Repair iniciado: {metadata_only_total} CFDIs metadata-only detectados",
            "counts": counts,
            "job_id": job_id,
            "checkpoint_reset_to": from_date,
        })

    @router.get("/sat/metadata-only-stats")
    def admin_metadata_only_stats(
        issuer_id: int,
        _admin: tuple[int, int, int | None] = Depends(require_admin),
    ):
        """Return metadata-only vs parsed CFDI counts for an issuer."""
        counts = count_metadata_only(issuer_id)
        cfdis = find_metadata_only_cfdis(issuer_id)
        return JSONResponse({
            "ok": True,
            "counts": counts,
            "metadata_only_cfdis": cfdis[:50],
            "total_metadata_only": len(cfdis),
        })
