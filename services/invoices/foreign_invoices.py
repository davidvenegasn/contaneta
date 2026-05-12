"""Foreign invoices — invoices/gastos de servicios internacionales."""

from database import db, db_rows, table_exists
from services.ym_helpers import is_annual


def ensure_table():
    """Create foreign_invoices table if missing (idempotent)."""
    conn = db()
    try:
        if not table_exists(conn, "foreign_invoices"):
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS foreign_invoices (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  issuer_id INTEGER NOT NULL,
                  tipo TEXT NOT NULL CHECK(tipo IN ('INGRESO','GASTO')),
                  fecha TEXT NOT NULL,
                  invoice_number TEXT NOT NULL,
                  empresa TEXT NOT NULL,
                  pais TEXT,
                  tax_id TEXT,
                  descripcion TEXT NOT NULL,
                  moneda TEXT NOT NULL DEFAULT 'USD',
                  monto_original REAL NOT NULL,
                  tipo_cambio REAL NOT NULL,
                  monto_mxn REAL NOT NULL,
                  forma_pago TEXT,
                  referencia_pago TEXT,
                  archivo TEXT,
                  notas TEXT,
                  period_month TEXT,
                  created_at TEXT NOT NULL DEFAULT (datetime('now')),
                  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_foreign_invoices_issuer ON foreign_invoices(issuer_id);
                CREATE INDEX IF NOT EXISTS idx_foreign_invoices_period ON foreign_invoices(issuer_id, period_month);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_foreign_invoices_dedup ON foreign_invoices(issuer_id, invoice_number, empresa);
                """
            )
        else:
            # Add dedup index if missing (existing tables)
            try:
                conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_foreign_invoices_dedup "
                    "ON foreign_invoices(issuer_id, invoice_number, empresa)"
                )
                conn.commit()
            except Exception:
                pass  # index already exists or duplicates prevent creation
    finally:
        conn.close()


def is_duplicate(issuer_id: int, invoice_number: str, empresa: str) -> bool:
    """Check if a foreign invoice with the same number+empresa already exists."""
    rows = db_rows(
        "SELECT 1 FROM foreign_invoices WHERE issuer_id = ? AND invoice_number = ? AND empresa = ? LIMIT 1",
        (issuer_id, invoice_number.strip(), empresa.strip()),
    )
    return len(rows) > 0


def create(issuer_id: int, tipo: str, fecha: str, invoice_number: str,
           empresa: str, descripcion: str, moneda: str, monto_original: float,
           tipo_cambio: float, forma_pago: str = None, pais: str = None,
           tax_id: str = None, referencia_pago: str = None,
           archivo: str = None, notas: str = None) -> dict:
    """Insert a foreign invoice and return it."""
    tipo = tipo.strip().upper()
    if tipo not in ("INGRESO", "GASTO"):
        raise ValueError("tipo must be INGRESO or GASTO")
    monto_mxn = round(monto_original * tipo_cambio, 2)
    period_month = fecha[:7] if fecha and len(fecha) >= 7 else None
    conn = db()
    try:
        cur = conn.execute(
            """
            INSERT INTO foreign_invoices
              (issuer_id, tipo, fecha, invoice_number, empresa, pais, tax_id,
               descripcion, moneda, monto_original, tipo_cambio, monto_mxn,
               forma_pago, referencia_pago, archivo, notas, period_month)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (issuer_id, tipo, fecha, invoice_number.strip(), empresa.strip(),
             pais, tax_id, descripcion.strip(), moneda, abs(monto_original),
             tipo_cambio, monto_mxn, forma_pago, referencia_pago, archivo,
             notas, period_month),
        )
        conn.commit()
        row_id = cur.lastrowid
    finally:
        conn.close()
    rows = db_rows("SELECT * FROM foreign_invoices WHERE id = ?", (row_id,))
    return rows[0] if rows else {"id": row_id}


def list_invoices(issuer_id: int, period_month: str = None, tipo: str = None,
                  limit: int = 200, offset: int = 0) -> list[dict]:
    """List foreign invoices for an issuer."""
    where = ["issuer_id = ?"]
    params: list = [issuer_id]
    if period_month:
        if is_annual(period_month):
            where.append("substr(period_month, 1, 4) = ?")
        else:
            where.append("period_month = ?")
        params.append(period_month)
    if tipo:
        where.append("tipo = ?")
        params.append(tipo.strip().upper())
    where_sql = " AND ".join(where)
    params.extend([limit, offset])
    return db_rows(
        f"SELECT * FROM foreign_invoices WHERE {where_sql} ORDER BY fecha DESC, id DESC LIMIT ? OFFSET ?",
        tuple(params),
    )


def count_invoices(issuer_id: int, period_month: str = None) -> int:
    """Count foreign invoices for an issuer."""
    where = ["issuer_id = ?"]
    params: list = [issuer_id]
    if period_month:
        if is_annual(period_month):
            where.append("substr(period_month, 1, 4) = ?")
        else:
            where.append("period_month = ?")
        params.append(period_month)
    where_sql = " AND ".join(where)
    rows = db_rows(f"SELECT COUNT(*) AS n FROM foreign_invoices WHERE {where_sql}", tuple(params))
    return rows[0]["n"] if rows else 0
