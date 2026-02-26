"""Conexiones y helpers para invoicing.db y catalogs.db."""
import os
import sqlite3

from config import CATALOGS_DB, DB_PATH


def _row_factory(cursor, row):
    """Devuelve cada fila como dict para que .get() funcione en todo el código."""
    return dict(zip([c[0] for c in cursor.description], row))


def db() -> sqlite3.Connection:
    """Conexión a invoicing.db con timeout y pragmas (ver migrations_runner)."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = _row_factory
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def db_rows(sql: str, params: tuple = ()) -> list[dict]:
    """Ejecuta SELECT y devuelve filas como list[dict]."""
    conn = db()
    try:
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def db_execute(sql: str, params: tuple = ()) -> None:
    """Ejecuta INSERT/UPDATE/DELETE y hace commit."""
    conn = db()
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    r = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
        (name,),
    ).fetchone()
    return bool(r)


def has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    for r in rows:
        if isinstance(r, dict):
            name = r.get("name")
        else:
            name = r[1] if len(r) > 1 else None
        if name == column:
            return True
    return False


def safe_update(conn: sqlite3.Connection, table: str, row_id: int, data: dict) -> None:
    """Actualiza solo columnas que existan en el schema actual."""
    if not data:
        return
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    cols = set()
    for r in rows:
        if isinstance(r, dict):
            name = r.get("name")
        else:
            name = r[1] if len(r) > 1 else None
        if name:
            cols.add(name)
    payload = {k: v for k, v in data.items() if k in cols}
    if not payload:
        return
    set_sql = ", ".join([f"{k} = ?" for k in payload.keys()])
    vals = list(payload.values()) + [row_id]
    conn.execute(f"UPDATE {table} SET {set_sql} WHERE id = ?", vals)


# ----------------------------
# Catálogos SAT (catalogs.db)
# ----------------------------

# Whitelist: solo estas tablas pueden usarse en list_catalog/search_catalog (evita inyección por nombre de tabla).
ALLOWED_CATALOG_TABLES = frozenset({
    "cfdi_40_formas_pago",
    "cfdi_40_metodos_pago",
    "cfdi_40_usos_cfdi",
    "cfdi_40_regimenes_fiscales",
    "cfdi_40_monedas",
    "cfdi_40_productos_servicios",
    "cfdi_40_claves_unidades",
})


def _check_catalog_table(table: str) -> None:
    """Lanza ValueError si table no está en la whitelist."""
    if table not in ALLOWED_CATALOG_TABLES:
        raise ValueError(f"Catalog table not allowed: {table!r}")


def db_catalogs() -> sqlite3.Connection:
    if not os.path.exists(CATALOGS_DB):
        raise FileNotFoundError(f"No existe catalogs.db en: {CATALOGS_DB}")
    conn = sqlite3.connect(CATALOGS_DB)
    conn.row_factory = lambda cursor, row: dict(zip([c[0] for c in cursor.description], row))
    return conn


def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def _pick_column(cols: set[str], candidates: list[str]) -> str:
    for c in candidates:
        if c in cols:
            return c
    raise KeyError(f"No se encontró ninguna columna de {candidates} en la tabla")


def list_catalog(table: str, order_by: str | None = None) -> list[dict]:
    """Devuelve [{"key": "...", "label": "..."}] de una tabla de catálogo SAT. table debe estar en ALLOWED_CATALOG_TABLES."""
    _check_catalog_table(table)
    con = db_catalogs()
    try:
        cols = _table_columns(con, table)
        key_col = _pick_column(cols, ["id", "clave", "key", "c_Clave"])
        label_col = _pick_column(cols, ["texto", "descripcion", "description", "value", "nombre"])
        ob = order_by or key_col
        rows = con.execute(
            f"SELECT {key_col} AS k, {label_col} AS v FROM {table} ORDER BY {ob}"
        ).fetchall()
        return [{"key": str(r["k"]), "label": str(r["v"])} for r in rows]
    finally:
        con.close()


def search_catalog(table: str, q: str, limit: int = 20) -> list[dict]:
    """Búsqueda en catálogos grandes (ProdServ, Unidad). table debe estar en ALLOWED_CATALOG_TABLES."""
    _check_catalog_table(table)
    con = db_catalogs()
    try:
        cols = _table_columns(con, table)
        key_col = _pick_column(cols, ["id", "clave", "key"])
        label_col = _pick_column(cols, ["texto", "descripcion", "description", "value", "nombre"])
        rows = con.execute(
            f"""
            SELECT {key_col} AS k, {label_col} AS v
            FROM {table}
            WHERE ({label_col} LIKE ? OR {key_col} LIKE ?)
            LIMIT ?
            """,
            (f"%{q}%", f"%{q}%", int(limit)),
        ).fetchall()
        return [{"key": str(r["k"]), "label": str(r["v"])} for r in rows]
    finally:
        con.close()
