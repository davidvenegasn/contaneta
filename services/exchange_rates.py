"""Exchange rates by month — lookup and management."""

from database import db, db_rows

# Fallback rates when no DB record exists
_FALLBACK = {"USD": 20.0, "EUR": 22.0, "GBP": 25.5, "CAD": 14.5, "CHF": 23.0}


def get_rate(moneda: str, period_month: str) -> float:
    """Return exchange rate for a currency+month. Falls back to closest month, then hardcoded."""
    moneda = (moneda or "USD").upper().strip()
    period_month = (period_month or "")[:7]

    # Exact match
    rows = db_rows(
        "SELECT rate FROM exchange_rates WHERE moneda = ? AND period_month = ? LIMIT 1",
        (moneda, period_month),
    )
    if rows:
        return float(rows[0]["rate"])

    # Closest previous month
    rows = db_rows(
        "SELECT rate FROM exchange_rates WHERE moneda = ? AND period_month <= ? ORDER BY period_month DESC LIMIT 1",
        (moneda, period_month),
    )
    if rows:
        return float(rows[0]["rate"])

    # Closest any month
    rows = db_rows(
        "SELECT rate FROM exchange_rates WHERE moneda = ? ORDER BY period_month DESC LIMIT 1",
        (moneda,),
    )
    if rows:
        return float(rows[0]["rate"])

    return _FALLBACK.get(moneda, 20.0)


def set_rate(moneda: str, period_month: str, rate: float, source: str = "manual") -> None:
    """Insert or update an exchange rate."""
    conn = db()
    try:
        conn.execute(
            """INSERT INTO exchange_rates (moneda, period_month, rate, source, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))
               ON CONFLICT(moneda, period_month) DO UPDATE SET rate=excluded.rate, source=excluded.source, updated_at=datetime('now')""",
            (moneda.upper().strip(), period_month[:7], rate, source),
        )
        conn.commit()
    finally:
        conn.close()


def list_rates(moneda: str | None = None, limit: int = 50) -> list[dict]:
    """List exchange rates, optionally filtered by currency."""
    if moneda:
        return db_rows(
            "SELECT * FROM exchange_rates WHERE moneda = ? ORDER BY period_month DESC LIMIT ?",
            (moneda.upper(), limit),
        )
    return db_rows(
        "SELECT * FROM exchange_rates ORDER BY moneda, period_month DESC LIMIT ?",
        (limit,),
    )
