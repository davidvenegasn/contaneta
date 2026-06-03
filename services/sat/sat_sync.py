"""SAT sync status and month totals — shared logic extracted from routers."""
import logging

from database import db, has_column
from services.ym_helpers import ym_sql_filter

logger = logging.getLogger(__name__)

_RETENCIONES_WARNED = False


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
            "SELECT finished_at AS t, last_error FROM sat_jobs WHERE issuer_id = ? AND status = 'error' ORDER BY finished_at DESC LIMIT 1",
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


def get_month_totals(issuer_id: int, ym: str, direction: str, metodo_pago: str = None, *, conn=None) -> dict:
    """Totales del mes para emitidas o recibidas: base (subtotal), IVA y retenciones.

    Args:
        conn: Optional existing DB connection for atomic multi-call snapshots.
              If None, creates and closes its own connection.
    """
    _conn = conn or db()
    _close = conn is None
    try:
        base_where = (
            f"issuer_id = ? AND direction = ? AND fecha_emision IS NOT NULL AND {ym_sql_filter(ym)}"
        )
        if direction == "issued":
            base_where += " AND (xml_status = 'parsed' OR total IS NULL OR total >= 0.01)"
        else:
            base_where += " AND total IS NOT NULL AND total >= 0.01 AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')"
        base_where += (
            " AND COALESCE(UPPER(TRIM(status)), '') NOT IN ('C','CANCELADO','CANCELADA','0')"
            " AND UPPER(TRIM(COALESCE(status,''))) NOT LIKE 'CANCEL%'"
        )
        params: list = [issuer_id, direction, ym]
        if metodo_pago:
            base_where += " AND UPPER(TRIM(COALESCE(metodo_pago,''))) = ?"
            params.append(metodo_pago.upper().strip())
        has_retenciones = has_column(_conn, "sat_cfdi", "retenciones")
        global _RETENCIONES_WARNED
        if not has_retenciones and not _RETENCIONES_WARNED:
            logger.warning(
                "sat_cfdi table lacks 'retenciones' column — total_iva_neto will not account for retenciones"
            )
            _RETENCIONES_WARNED = True
        if has_retenciones:
            row = _conn.execute(
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
            row = _conn.execute(
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
        result = {
            "total_base": total_base,
            "total_iva": total_iva,
            "total_retenciones": total_retenciones,
            "total_iva_neto": max(0.0, total_iva - total_retenciones) if direction == "issued" else total_iva,
        }
        logger.debug(
            "KPI issuer=%s ym=%s dir=%s base=%.2f iva=%.2f ret=%.2f neto=%.2f",
            issuer_id, ym, direction,
            total_base, total_iva, total_retenciones, result["total_iva_neto"],
        )
        return result
    finally:
        if _close:
            _conn.close()
