"""Manual movements — user-entered income/expense records."""

from database import db, db_execute, db_rows, table_exists


def ensure_table():
    """Create manual_movements table if missing (idempotent)."""
    conn = db()
    try:
        if not table_exists(conn, "manual_movements"):
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS manual_movements (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  issuer_id INTEGER NOT NULL,
                  fecha TEXT NOT NULL,
                  descripcion TEXT NOT NULL,
                  monto REAL NOT NULL,
                  tipo TEXT NOT NULL CHECK(tipo IN ('INGRESO','GASTO')),
                  categoria TEXT,
                  notas TEXT,
                  period_month TEXT,
                  forma_pago TEXT,
                  contraparte TEXT,
                  moneda TEXT DEFAULT 'MXN',
                  created_at TEXT NOT NULL DEFAULT (datetime('now')),
                  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_manual_movements_issuer ON manual_movements(issuer_id);
                CREATE INDEX IF NOT EXISTS idx_manual_movements_period ON manual_movements(issuer_id, period_month);
                """
            )
        else:
            # Ensure new columns exist on older tables
            cur = conn.execute("PRAGMA table_info(manual_movements)")
            cols = {row["name"] for row in cur.fetchall()}
            if "forma_pago" not in cols:
                conn.execute("ALTER TABLE manual_movements ADD COLUMN forma_pago TEXT")
            if "contraparte" not in cols:
                conn.execute("ALTER TABLE manual_movements ADD COLUMN contraparte TEXT")
            if "moneda" not in cols:
                conn.execute("ALTER TABLE manual_movements ADD COLUMN moneda TEXT DEFAULT 'MXN'")
            conn.commit()
    finally:
        conn.close()


def create(issuer_id: int, fecha: str, descripcion: str, monto: float, tipo: str,
           categoria: str = None, notas: str = None,
           forma_pago: str = None, contraparte: str = None,
           moneda: str = "MXN") -> dict:
    """Insert a manual movement and return it."""
    tipo = tipo.strip().upper()
    if tipo not in ("INGRESO", "GASTO"):
        raise ValueError("tipo must be INGRESO or GASTO")
    period_month = fecha[:7] if fecha and len(fecha) >= 7 else None
    moneda = (moneda or "MXN").upper().strip()
    conn = db()
    try:
        cur = conn.execute(
            """
            INSERT INTO manual_movements (issuer_id, fecha, descripcion, monto, tipo, categoria, notas, period_month, forma_pago, contraparte, moneda)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (issuer_id, fecha, descripcion.strip(), abs(monto), tipo, categoria, notas, period_month, forma_pago, contraparte, moneda),
        )
        conn.commit()
        row_id = cur.lastrowid
    finally:
        conn.close()
    rows = db_rows("SELECT * FROM manual_movements WHERE id = ?", (row_id,))
    return rows[0] if rows else {"id": row_id}


def list_movements(issuer_id: int, period_month: str = None, tipo: str = None,
                   limit: int = 200, offset: int = 0) -> list[dict]:
    """List manual movements for an issuer, optionally filtered."""
    where = ["issuer_id = ?"]
    params: list = [issuer_id]
    if period_month:
        where.append("period_month = ?")
        params.append(period_month)
    if tipo:
        where.append("tipo = ?")
        params.append(tipo.strip().upper())
    where_sql = " AND ".join(where)
    params.extend([limit, offset])
    return db_rows(
        f"SELECT * FROM manual_movements WHERE {where_sql} ORDER BY fecha DESC, id DESC LIMIT ? OFFSET ?",
        tuple(params),
    )


def count_movements(issuer_id: int, period_month: str = None) -> int:
    """Count manual movements for an issuer."""
    where = ["issuer_id = ?"]
    params: list = [issuer_id]
    if period_month:
        where.append("period_month = ?")
        params.append(period_month)
    where_sql = " AND ".join(where)
    rows = db_rows(f"SELECT COUNT(*) AS n FROM manual_movements WHERE {where_sql}", tuple(params))
    return rows[0]["n"] if rows else 0


def get_sums(issuer_id: int, period_month: str = None) -> dict:
    """Return sum of ingresos and gastos for the period."""
    where = ["issuer_id = ?"]
    params: list = [issuer_id]
    if period_month:
        where.append("period_month = ?")
        params.append(period_month)
    where_sql = " AND ".join(where)
    rows = db_rows(
        f"""
        SELECT
            COALESCE(SUM(CASE WHEN tipo='INGRESO' THEN monto ELSE 0 END), 0) AS ingresos,
            COALESCE(SUM(CASE WHEN tipo='GASTO' THEN monto ELSE 0 END), 0) AS gastos
        FROM manual_movements WHERE {where_sql}
        """,
        tuple(params),
    )
    return rows[0] if rows else {"ingresos": 0, "gastos": 0}


def delete(issuer_id: int, movement_id: int) -> bool:
    """Delete a manual movement. Returns True if deleted."""
    conn = db()
    try:
        cur = conn.execute(
            "DELETE FROM manual_movements WHERE id = ? AND issuer_id = ?",
            (movement_id, issuer_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
