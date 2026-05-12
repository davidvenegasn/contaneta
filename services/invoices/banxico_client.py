"""Banxico DOF exchange rate client with DB cache.

Fetches official MXN exchange rates from Banco de México's SIE API.
Rates are published on business days only; for weekends/holidays,
the SAT rule is to use the last published rate.

Requires BANXICO_TOKEN env var (free registration at https://www.banxico.org.mx/SieAPIRest/).
"""

import json
import logging
import os
import urllib.request
from datetime import date, timedelta

from database import db_execute, db_rows

logger = logging.getLogger(__name__)

BANXICO_SERIES = {
    "USD": "SF43718",  # FIX para liquidar obligaciones en USD
    "EUR": "SF46410",
    "GBP": "SF60632",
    "JPY": "SF46406",
    "CAD": "SF46408",
    "CHF": "SF46407",
}

BANXICO_BASE = "https://www.banxico.org.mx/SieAPIRest/service/v1/series"


class BanxicoError(Exception):
    pass


def _fetch_from_banxico(currency: str, fecha_iso: str) -> float | None:
    """Fetch rate from Banxico API for a given currency and date.

    Fetches a 7-day window ending on fecha_iso to handle weekends/holidays.
    Caches results in exchange_rates table.
    Returns the rate or None if unavailable.
    """
    token = os.getenv("BANXICO_TOKEN", "").strip()
    if not token:
        logger.warning("BANXICO_TOKEN not set; cannot fetch real rates")
        return None
    series = BANXICO_SERIES.get(currency.upper())
    if not series:
        return None
    # Fetch window: 7 days before to fecha to catch DOF rates if weekend
    d = date.fromisoformat(fecha_iso)
    start = (d - timedelta(days=7)).isoformat()
    url = f"{BANXICO_BASE}/{series}/datos/{start}/{fecha_iso}"
    req = urllib.request.Request(
        url,
        headers={"Bmx-Token": token, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.exception("Banxico fetch failed: %s", e)
        return None
    try:
        datos = data["bmx"]["series"][0]["datos"]
        if not datos:
            return None
        # Banxico returns chronological. Pick last available <= fecha_iso.
        # Format: {"fecha": "DD/MM/YYYY", "dato": "17.4523"}
        rates = []
        for row in datos:
            fecha_es = row.get("fecha")  # DD/MM/YYYY
            dato = row.get("dato")
            if not dato or dato == "N/E":
                continue
            dd, mm, yyyy = fecha_es.split("/")
            iso_fecha = f"{yyyy}-{mm}-{dd}"
            if iso_fecha <= fecha_iso:
                rates.append((iso_fecha, float(dato)))
        if not rates:
            return None
        rates.sort()
        best_date, best_rate = rates[-1]
        # Cache the EXACT date Banxico published
        _cache_rate(best_date, currency.upper(), best_rate, series)
        # If user asked for a date Banxico hasn't published (weekend),
        # also cache the user's date with the same rate
        if best_date != fecha_iso:
            _cache_rate(
                fecha_iso, currency.upper(), best_rate, series,
                source="banxico_dof_nearest",
            )
        return best_rate
    except (KeyError, ValueError, TypeError) as e:
        logger.exception("Banxico response parse failed: %s", e)
        return None


def _cache_rate(
    fecha_iso: str, currency: str, rate: float, series: str,
    source: str = "banxico_dof",
) -> None:
    """Insert rate into exchange_rates cache (ignore if already exists)."""
    db_execute(
        "INSERT OR IGNORE INTO dof_rates "
        "(date, currency, rate_to_mxn, source, series) VALUES (?, ?, ?, ?, ?)",
        (fecha_iso, currency, rate, source, series),
    )


def get_rate(fecha_iso: str, currency: str) -> float | None:
    """Get MXN exchange rate for currency on given date.

    Strategy: cache-first, then Banxico API, then nearest cached rate (30 days).
    Returns None if no rate available (caller must fallback).
    """
    currency = currency.upper().strip()
    if currency == "MXN":
        return 1.0
    # 1. Try exact cache hit
    rows = db_rows(
        "SELECT rate_to_mxn FROM dof_rates "
        "WHERE date = ? AND currency = ? LIMIT 1",
        (fecha_iso, currency),
    )
    if rows:
        return float(rows[0]["rate_to_mxn"])
    # 2. Try Banxico API
    rate = _fetch_from_banxico(currency, fecha_iso)
    if rate is not None:
        return rate
    # 3. Fallback to nearest previous cached date (max 30 days back)
    d = date.fromisoformat(fecha_iso)
    start = (d - timedelta(days=30)).isoformat()
    rows = db_rows(
        "SELECT rate_to_mxn FROM dof_rates "
        "WHERE currency = ? AND date <= ? AND date >= ? "
        "ORDER BY date DESC LIMIT 1",
        (currency, fecha_iso, start),
    )
    if rows:
        return float(rows[0]["rate_to_mxn"])
    return None
