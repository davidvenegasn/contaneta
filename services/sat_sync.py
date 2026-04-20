"""SAT sync status and month totals — shared logic extracted from routers."""
import logging

from database import db, has_column

logger = logging.getLogger(__name__)


def get_sat_sync_status(issuer_id: int) -> dict:
    """Estado del sync SAT para un issuer: last_sync_at, status (running|ok|error), message."""
    conn = db()
    try:
        running = conn.execute(
            "SELECT created_at FROM sat_jobs WHERE issuer_id = ? AND status IN ('queued','running') ORDER BY created_at ASC LIMIT 1",
            (issuer_id,),
        ).fetchone()
        last_ok = conn.execute(
            "SELECT MAX(finished_at) AS t FROM sat_jobs WHERE issuer_id = ? AND status = 'ok'",
            (issuer_id,),
        ).fetchone()
        last_error = conn.execute(
            "SELECT finished_at, last_error FROM sat_jobs WHERE issuer_id = ? AND status = 'error' ORDER BY finished_at DESC LIMIT 1",
            (issuer_id,),
        ).fetchone()
        sync_state = conn.execute(
            "SELECT MAX(last_run_at) AS t FROM sat_sync_state WHERE issuer_id = ?",
            (issuer_id,),
        ).fetchone()
    finally:
        conn.close()
    last_sync_at = (sync_state and sync_state["t"]) or (last_ok and last_ok["t"]) or None
    if running:
        status = "running"
        message = "Sincronización en proceso"
        # Check if job has been running too long (>10 min)
        try:
            from datetime import datetime, timezone
            started = running["created_at"]
            if started:
                started_dt = datetime.fromisoformat(started.replace("Z", "+00:00")) if "T" in started else datetime.strptime(started[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                elapsed = (datetime.now(timezone.utc) - started_dt).total_seconds()
                if elapsed > 600:  # 10 minutes
                    status = "stale"
                    message = "La sincronización tardó más de lo esperado. Puedes reintentar."
        except Exception:
            pass
    elif last_error and last_ok and last_error["t"] and last_ok["t"] and last_error["t"] > last_ok["t"]:
        status = "error"
        message = (last_error["last_error"] or "Error en la última sincronización")[:200]
    elif last_error and not last_ok:
        status = "error"
        message = (last_error["last_error"] or "Error en la última sincronización")[:200]
    else:
        status = "ok"
        message = None
    return {"last_sync_at": last_sync_at, "status": status, "message": message}


def get_month_totals(issuer_id: int, ym: str, direction: str) -> dict:
    """Totales del mes para emitidas o recibidas: base (subtotal), IVA y retenciones."""
    conn = db()
    try:
        base_where = (
            "issuer_id = ? AND direction = ? AND fecha_emision IS NOT NULL AND substr(fecha_emision,1,7) = ?"
        )
        if direction == "issued":
            base_where += " AND (total IS NULL OR total >= 0.01)"
        else:
            base_where += " AND total IS NOT NULL AND total >= 0.01 AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')"
        params = (issuer_id, direction, ym)
        has_retenciones = has_column(conn, "sat_cfdi", "retenciones")
        if has_retenciones:
            row = conn.execute(
                f"""
                SELECT
                    COALESCE(SUM(COALESCE(subtotal, total)), 0) AS total_base,
                    COALESCE(SUM(COALESCE(impuestos, 0)), 0) AS total_iva,
                    COALESCE(SUM(COALESCE(retenciones, 0)), 0) AS total_retenciones
                FROM sat_cfdi
                WHERE {base_where}
                """,
                params,
            ).fetchone()
        else:
            row = conn.execute(
                f"""
                SELECT
                    COALESCE(SUM(COALESCE(subtotal, total)), 0) AS total_base,
                    COALESCE(SUM(COALESCE(impuestos, 0)), 0) AS total_iva
                FROM sat_cfdi
                WHERE {base_where}
                """,
                params,
            ).fetchone()
        if not row:
            total_base = total_iva = total_retenciones = 0.0
        else:
            total_base = float(row.get("total_base") or 0)
            total_iva = float(row.get("total_iva") or 0)
            total_retenciones = float(row.get("total_retenciones") or 0) if has_retenciones else 0.0
        return {
            "total_base": total_base,
            "total_iva": total_iva,
            "total_retenciones": total_retenciones,
            "total_iva_neto": max(0.0, total_iva - total_retenciones) if direction == "issued" else total_iva,
        }
    finally:
        conn.close()
