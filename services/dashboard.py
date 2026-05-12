"""Dashboard service — actionable metrics, alerts, and next-actions for the portal home."""
import logging
from datetime import date, timedelta

from database import db, db_rows, has_column, table_exists
from services.ym_helpers import shift_ym, ym_to_label

logger = logging.getLogger(__name__)


def _current_quarter_bounds() -> tuple[str, str]:
    """Return (start_date, end_date) for the current calendar quarter as YYYY-MM-DD strings."""
    today = date.today()
    q = (today.month - 1) // 3
    start_month = q * 3 + 1
    start = date(today.year, start_month, 1)
    # End is the last day of the quarter
    if start_month + 3 > 12:
        end = date(today.year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(today.year, start_month + 3, 1) - timedelta(days=1)
    return start.isoformat(), end.isoformat()


def get_monthly_trend(issuer_id: int, months: int = 12) -> list[dict]:
    """Return month-by-month totals (ingresos, gastos) for the last N months.

    Queries sat_cfdi grouped by substr(fecha_emision, 1, 7).
    Returns a list of dicts with keys: ym, label, ingresos, gastos.
    Months with no data are included with zero values.

    Args:
        issuer_id: Tenant ID.
        months: Number of months to include (default 12).

    Returns:
        List of dicts ordered chronologically (oldest first).
    """
    MESES = [
        "Ene", "Feb", "Mar", "Abr", "May", "Jun",
        "Jul", "Ago", "Sep", "Oct", "Nov", "Dic",
    ]
    today = date.today()
    # Build list of last N months (inclusive of current)
    ym_list = []
    y, m = today.year, today.month
    for _ in range(months):
        ym_list.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m <= 0:
            m = 12
            y -= 1
    ym_list.reverse()

    # Fetch issued totals grouped by month
    issued_rows = db_rows(
        """
        SELECT substr(fecha_emision, 1, 7) AS ym,
               COALESCE(SUM(COALESCE(total, 0)), 0) AS total
        FROM sat_cfdi
        WHERE issuer_id = ? AND direction = 'issued'
          AND fecha_emision IS NOT NULL
          AND (total IS NULL OR total >= 0.01)
          AND substr(fecha_emision, 1, 7) >= ?
        GROUP BY substr(fecha_emision, 1, 7)
        """,
        (issuer_id, ym_list[0]),
    )
    # Fetch received totals grouped by month
    received_rows = db_rows(
        """
        SELECT substr(fecha_emision, 1, 7) AS ym,
               COALESCE(SUM(COALESCE(total, 0)), 0) AS total
        FROM sat_cfdi
        WHERE issuer_id = ? AND direction = 'received'
          AND fecha_emision IS NOT NULL
          AND total IS NOT NULL AND total >= 0.01
          AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
          AND substr(fecha_emision, 1, 7) >= ?
        GROUP BY substr(fecha_emision, 1, 7)
        """,
        (issuer_id, ym_list[0]),
    )

    issued_map = {r["ym"]: float(r["total"]) for r in issued_rows}
    received_map = {r["ym"]: float(r["total"]) for r in received_rows}

    result = []
    for ym in ym_list:
        parts = ym.split("-")
        mi = int(parts[1]) - 1
        label = f"{MESES[mi]} {parts[0][2:]}" if 0 <= mi < 12 else ym
        result.append({
            "ym": ym,
            "label": label,
            "ingresos": issued_map.get(ym, 0),
            "gastos": received_map.get(ym, 0),
        })
    return result


def get_top_clients(issuer_id: int, limit: int = 5) -> list[dict]:
    """Top N clients by invoiced amount (issued CFDIs) for the current quarter.

    Args:
        issuer_id: Tenant ID.
        limit: Max number of results.

    Returns:
        List of dicts with keys: nombre, rfc, total, count.
    """
    start, end = _current_quarter_bounds()
    rows = db_rows(
        """
        SELECT COALESCE(nombre_receptor, rfc_receptor) AS nombre,
               rfc_receptor AS rfc,
               SUM(COALESCE(total, 0)) AS total,
               COUNT(*) AS count
        FROM sat_cfdi
        WHERE issuer_id = ? AND direction = 'issued'
          AND fecha_emision IS NOT NULL
          AND fecha_emision >= ? AND fecha_emision <= ?
          AND (total IS NULL OR total >= 0.01)
        GROUP BY rfc_receptor
        ORDER BY total DESC
        LIMIT ?
        """,
        (issuer_id, start, end + "T23:59:59", limit),
    )
    return [
        {
            "nombre": (r.get("nombre") or "Sin nombre").strip(),
            "rfc": (r.get("rfc") or "").strip(),
            "total": float(r.get("total") or 0),
            "count": int(r.get("count") or 0),
        }
        for r in rows
    ]


def get_top_providers(issuer_id: int, limit: int = 5) -> list[dict]:
    """Top N providers by expense amount (received CFDIs) for the current quarter.

    Args:
        issuer_id: Tenant ID.
        limit: Max number of results.

    Returns:
        List of dicts with keys: nombre, rfc, total, count.
    """
    start, end = _current_quarter_bounds()
    rows = db_rows(
        """
        SELECT COALESCE(nombre_emisor, rfc_emisor) AS nombre,
               rfc_emisor AS rfc,
               SUM(COALESCE(total, 0)) AS total,
               COUNT(*) AS count
        FROM sat_cfdi
        WHERE issuer_id = ? AND direction = 'received'
          AND fecha_emision IS NOT NULL
          AND fecha_emision >= ? AND fecha_emision <= ?
          AND total IS NOT NULL AND total >= 0.01
          AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
        GROUP BY rfc_emisor
        ORDER BY total DESC
        LIMIT ?
        """,
        (issuer_id, start, end + "T23:59:59", limit),
    )
    return [
        {
            "nombre": (r.get("nombre") or "Sin nombre").strip(),
            "rfc": (r.get("rfc") or "").strip(),
            "total": float(r.get("total") or 0),
            "count": int(r.get("count") or 0),
        }
        for r in rows
    ]


def get_alerts(issuer_id: int, ym: str) -> list[dict]:
    """Build actionable alert cards for the dashboard.

    Each alert is a dict with keys: key, title, subtitle, count, total, href, severity.
    severity is 'warning' or 'info'.

    Args:
        issuer_id: Tenant ID.
        ym: Current year-month (YYYY-MM).

    Returns:
        List of alert dicts. Empty list means all clear.
    """
    alerts = []

    # Alert 1: PPD CFDIs without payment complement > 30 days
    try:
        _ppd_alert = _check_ppd_pending(issuer_id)
        if _ppd_alert:
            alerts.append(_ppd_alert)
    except Exception:
        logger.debug("dashboard alert: ppd check failed", exc_info=True)

    # Alert 2: Bank movements without matched CFDI this month
    try:
        _bank_alert = _check_unmatched_bank_movements(issuer_id, ym)
        if _bank_alert:
            alerts.append(_bank_alert)
    except Exception:
        logger.debug("dashboard alert: bank movements check failed", exc_info=True)

    # Alert 3: Previous month not closed
    try:
        _close_alert = _check_prev_month_not_closed(issuer_id, ym)
        if _close_alert:
            alerts.append(_close_alert)
    except Exception:
        logger.debug("dashboard alert: month close check failed", exc_info=True)

    # Alert 4: Unsynced / invalid SAT credentials
    try:
        _cred_alert = _check_unsynced_sat_credentials(issuer_id)
        if _cred_alert:
            alerts.append(_cred_alert)
    except Exception:
        logger.debug("dashboard alert: sat credentials check failed", exc_info=True)

    # Alert 5: Cancelled invoices in current month
    try:
        _cancel_alert = _check_cancelled_invoices(issuer_id, ym)
        if _cancel_alert:
            alerts.append(_cancel_alert)
    except Exception:
        logger.debug("dashboard alert: cancelled invoices check failed", exc_info=True)

    # Alert 6: Missing fiscal profile
    try:
        _fiscal_alert = _check_missing_fiscal_profile(issuer_id)
        if _fiscal_alert:
            alerts.append(_fiscal_alert)
    except Exception:
        logger.debug("dashboard alert: fiscal profile check failed", exc_info=True)

    return alerts


def _check_ppd_pending(issuer_id: int) -> dict | None:
    """Check for PPD-method issued CFDIs older than 30 days without payment complement."""
    conn = db()
    try:
        # Check if metodo_pago column exists
        if not has_column(conn, "sat_cfdi", "metodo_pago"):
            return None

        cutoff = (date.today() - timedelta(days=30)).isoformat()
        rows = conn.execute(
            """
            SELECT COUNT(*) AS cnt,
                   COALESCE(SUM(COALESCE(total, 0)), 0) AS total_amount
            FROM sat_cfdi
            WHERE issuer_id = ? AND direction = 'issued'
              AND UPPER(TRIM(COALESCE(metodo_pago, ''))) = 'PPD'
              AND fecha_emision IS NOT NULL
              AND fecha_emision < ?
              AND (total IS NULL OR total >= 0.01)
              AND COALESCE(status, '') NOT IN ('cancelled', 'cancelado', 'Cancelado')
            """,
            (issuer_id, cutoff),
        ).fetchone()
        if not rows:
            return None
        cnt = int(rows.get("cnt") or 0)
        total_amount = float(rows.get("total_amount") or 0)
        if cnt == 0:
            return None
        return {
            "key": "ppd_pending",
            "title": f"{cnt} factura{'s' if cnt != 1 else ''} PPD sin complemento de pago",
            "subtitle": f"Total: ${total_amount:,.0f} — Más de 30 días sin pago registrado",
            "count": cnt,
            "total": total_amount,
            "href": "/portal/facturas?tab=issued&metodo=PPD",
            "severity": "warning",
        }
    finally:
        conn.close()


def _check_unmatched_bank_movements(issuer_id: int, ym: str) -> dict | None:
    """Check for bank movements in the current month without a matched CFDI."""
    conn = db()
    try:
        if not table_exists(conn, "bank_movements"):
            return None

        # Check if period_month column exists
        has_period = has_column(conn, "bank_movements", "period_month")
        if has_period:
            row = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM bank_movements
                WHERE issuer_id = ? AND period_month = ?
                """,
                (issuer_id, ym),
            ).fetchone()
        else:
            # Fall back to substr of fecha
            row = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM bank_movements
                WHERE issuer_id = ? AND substr(fecha, 1, 7) = ?
                """,
                (issuer_id, ym),
            ).fetchone()

        cnt = int(row.get("cnt") or 0) if row else 0
        if cnt == 0:
            return None

        # Count unmatched (no cfdi_uuid linkage — if column exists, else all are "unmatched")
        has_cfdi_col = has_column(conn, "bank_movements", "cfdi_uuid")
        if has_cfdi_col:
            if has_period:
                unmatched_row = conn.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM bank_movements
                    WHERE issuer_id = ? AND period_month = ?
                      AND (cfdi_uuid IS NULL OR TRIM(cfdi_uuid) = '')
                    """,
                    (issuer_id, ym),
                ).fetchone()
            else:
                unmatched_row = conn.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM bank_movements
                    WHERE issuer_id = ? AND substr(fecha, 1, 7) = ?
                      AND (cfdi_uuid IS NULL OR TRIM(cfdi_uuid) = '')
                    """,
                    (issuer_id, ym),
                ).fetchone()
            unmatched = int(unmatched_row.get("cnt") or 0) if unmatched_row else 0
        else:
            # No cfdi_uuid column, assume all unmatched
            unmatched = cnt

        if unmatched == 0:
            return None

        return {
            "key": "bank_unmatched",
            "title": f"{unmatched} movimiento{'s' if unmatched != 1 else ''} bancario{'s' if unmatched != 1 else ''} sin CFDI",
            "subtitle": f"Del mes actual — {unmatched} de {cnt} sin factura asociada",
            "count": unmatched,
            "total": 0,
            "href": "/portal/movimientos",
            "severity": "info",
        }
    finally:
        conn.close()


def _check_prev_month_not_closed(issuer_id: int, ym: str) -> dict | None:
    """Check if the previous month is not yet closed."""
    prev_ym = shift_ym(ym, -1)
    conn = db()
    try:
        if not table_exists(conn, "month_close_status"):
            return None

        row = conn.execute(
            "SELECT status_json FROM month_close_status WHERE issuer_id = ? AND ym = ? LIMIT 1",
            (issuer_id, prev_ym),
        ).fetchone()

        if row and row.get("status_json"):
            import json
            try:
                data = json.loads(row["status_json"])
                if isinstance(data, dict) and data.get("closed"):
                    return None
            except Exception:
                pass

        # Check if prev month has any data at all
        has_data = conn.execute(
            """
            SELECT 1 FROM sat_cfdi
            WHERE issuer_id = ? AND substr(fecha_emision, 1, 7) = ?
            LIMIT 1
            """,
            (issuer_id, prev_ym),
        ).fetchone()

        if not has_data:
            return None

        label = ym_to_label(prev_ym)

        return {
            "key": "prev_month_open",
            "title": f"{label} sin cerrar",
            "subtitle": "Revisa y cierra el mes anterior para mantener tu contabilidad al día",
            "count": 0,
            "total": 0,
            "href": f"/portal/month-close?ym={prev_ym}",
            "severity": "info",
        }
    finally:
        conn.close()


def get_next_actions(issuer_id: int, ym: str) -> list[dict]:
    """Build the next-actions checklist for the dashboard.

    Each action is a dict with keys: key, label, done, href.

    Args:
        issuer_id: Tenant ID.
        ym: Current year-month (YYYY-MM).

    Returns:
        List of action dicts.
    """
    actions = []

    # 1. Upload bank statement for the month
    has_statement = False
    try:
        conn = db()
        if table_exists(conn, "bank_movements"):
            has_period = has_column(conn, "bank_movements", "period_month")
            if has_period:
                r = conn.execute(
                    "SELECT 1 FROM bank_movements WHERE issuer_id = ? AND period_month = ? LIMIT 1",
                    (issuer_id, ym),
                ).fetchone()
            else:
                r = conn.execute(
                    "SELECT 1 FROM bank_movements WHERE issuer_id = ? AND substr(fecha, 1, 7) = ? LIMIT 1",
                    (issuer_id, ym),
                ).fetchone()
            has_statement = bool(r)
        conn.close()
    except Exception:
        pass

    actions.append({
        "key": "upload_bank",
        "label": "Subir estado de cuenta del mes",
        "done": has_statement,
        "href": "/portal/convertir-edo-cuenta",
    })

    # 2. Reconcile pending movements
    pending_count = 0
    try:
        conn = db()
        if table_exists(conn, "bank_movements"):
            has_period = has_column(conn, "bank_movements", "period_month")
            has_cfdi = has_column(conn, "bank_movements", "cfdi_uuid")
            if has_period and has_cfdi:
                r = conn.execute(
                    """
                    SELECT COUNT(*) AS cnt FROM bank_movements
                    WHERE issuer_id = ? AND period_month = ?
                      AND (cfdi_uuid IS NULL OR TRIM(cfdi_uuid) = '')
                    """,
                    (issuer_id, ym),
                ).fetchone()
                pending_count = int(r.get("cnt") or 0) if r else 0
            elif has_period:
                r = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM bank_movements WHERE issuer_id = ? AND period_month = ?",
                    (issuer_id, ym),
                ).fetchone()
                pending_count = int(r.get("cnt") or 0) if r else 0
        conn.close()
    except Exception:
        pass

    actions.append({
        "key": "reconcile",
        "label": f"Conciliar {pending_count} movimiento{'s' if pending_count != 1 else ''} pendiente{'s' if pending_count != 1 else ''}" if pending_count > 0 else "Conciliar movimientos del mes",
        "done": has_statement and pending_count == 0,
        "href": "/portal/movimientos",
    })

    # 3. Close previous month
    prev_closed = False
    prev_ym = shift_ym(ym, -1)
    try:
        conn = db()
        if table_exists(conn, "month_close_status"):
            row = conn.execute(
                "SELECT status_json FROM month_close_status WHERE issuer_id = ? AND ym = ? LIMIT 1",
                (issuer_id, prev_ym),
            ).fetchone()
            if row and row.get("status_json"):
                import json
                data = json.loads(row["status_json"])
                if isinstance(data, dict) and data.get("closed"):
                    prev_closed = True
        conn.close()
    except Exception:
        pass

    prev_label = ym_to_label(prev_ym)

    actions.append({
        "key": "close_prev_month",
        "label": f"Cerrar mes anterior ({prev_label})",
        "done": prev_closed,
        "href": f"/portal/month-close?ym={prev_ym}",
    })

    # 4. Review month's taxes
    actions.append({
        "key": "review_taxes",
        "label": "Revisar impuestos del mes",
        "done": False,
        "href": f"/portal/fiscal?ym={ym}",
    })

    return actions


# ---------------------------------------------------------------------------
# New alert helpers
# ---------------------------------------------------------------------------

def _check_unsynced_sat_credentials(issuer_id: int) -> dict | None:
    """Check for SAT credentials that have not been validated (validation_ok = 0 or NULL)."""
    conn = db()
    try:
        if not table_exists(conn, "sat_credentials"):
            return None

        has_validation = has_column(conn, "sat_credentials", "validation_ok")
        if not has_validation:
            # Column doesn't exist — cannot check
            return None

        row = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM sat_credentials
            WHERE issuer_id = ?
              AND (validation_ok IS NULL OR validation_ok = 0)
            """,
            (issuer_id,),
        ).fetchone()

        cnt = int(row.get("cnt") or 0) if row else 0
        if cnt == 0:
            return None

        return {
            "key": "sat_credentials_unsynced",
            "title": "Credenciales SAT sin validar",
            "subtitle": "Tu FIEL no ha sido validada correctamente. Revísala para habilitar la sincronización.",
            "count": cnt,
            "total": 0,
            "href": "/portal/config/sat",
            "severity": "warning",
        }
    finally:
        conn.close()


def _check_cancelled_invoices(issuer_id: int, ym: str) -> dict | None:
    """Check for invoices with status 'cancelado' in the current month."""
    conn = db()
    try:
        if not has_column(conn, "sat_cfdi", "status"):
            return None

        row = conn.execute(
            """
            SELECT COUNT(*) AS cnt,
                   COALESCE(SUM(COALESCE(total, 0)), 0) AS total_amount
            FROM sat_cfdi
            WHERE issuer_id = ?
              AND substr(fecha_emision, 1, 7) = ?
              AND LOWER(TRIM(COALESCE(status, ''))) IN ('cancelado', 'cancelled')
            """,
            (issuer_id, ym),
        ).fetchone()

        cnt = int(row.get("cnt") or 0) if row else 0
        total_amount = float(row.get("total_amount") or 0) if row else 0
        if cnt == 0:
            return None

        return {
            "key": "cancelled_invoices",
            "title": f"{cnt} factura{'s' if cnt != 1 else ''} cancelada{'s' if cnt != 1 else ''} este mes",
            "subtitle": f"Total: ${total_amount:,.0f} — Revisa si requieren sustitución",
            "count": cnt,
            "total": total_amount,
            "href": f"/portal/facturas?status=cancelado&ym={ym}",
            "severity": "info",
        }
    finally:
        conn.close()


def _check_missing_fiscal_profile(issuer_id: int) -> dict | None:
    """Check if the issuer is missing a fiscal profile (no row in issuer_fiscal_profile)."""
    conn = db()
    try:
        if not table_exists(conn, "issuer_fiscal_profile"):
            return None

        row = conn.execute(
            "SELECT 1 FROM issuer_fiscal_profile WHERE issuer_id = ? LIMIT 1",
            (issuer_id,),
        ).fetchone()

        if row:
            return None

        # Only alert if the issuer has some CFDI data (avoid noise for brand new accounts)
        has_data = conn.execute(
            "SELECT 1 FROM sat_cfdi WHERE issuer_id = ? LIMIT 1",
            (issuer_id,),
        ).fetchone()

        if not has_data:
            return None

        return {
            "key": "missing_fiscal_profile",
            "title": "Perfil fiscal no configurado",
            "subtitle": "Configura tu régimen fiscal para obtener estimaciones de impuestos más precisas.",
            "count": 0,
            "total": 0,
            "href": "/portal/fiscal",
            "severity": "info",
        }
    finally:
        conn.close()
