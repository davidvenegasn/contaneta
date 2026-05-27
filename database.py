"""Conexiones y helpers para invoicing.db y catalogs.db."""
import logging
import os
import random
import sqlite3
import time
from contextlib import contextmanager

from config import CATALOGS_DB, DB_PATH

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY = 0.05  # 50ms


def _row_factory(cursor, row):
    """Devuelve cada fila como dict para que .get() funcione en todo el código."""
    return dict(zip([c[0] for c in cursor.description], row))


def db() -> sqlite3.Connection:
    """Conexión a invoicing.db con timeout y pragmas (ver migrations_runner)."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = _row_factory
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA wal_autocheckpoint = 1000;")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    """
    Context manager de transacción explícita.
    Uso:
        conn = db()
        with transaction(conn):
            conn.execute(...)
            conn.execute(...)
    Hace COMMIT si todo sale bien; ROLLBACK si hay excepción.
    """
    try:
        conn.execute("BEGIN")
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            logger.warning("transaction rollback failed", exc_info=True)
        raise


def _is_locked_error(e: Exception) -> bool:
    """Return True if the exception is a SQLite 'database is locked' error."""
    return isinstance(e, sqlite3.OperationalError) and "locked" in str(e).lower()


def db_rows(sql: str, params: tuple = ()) -> list[dict]:
    """Ejecuta SELECT y devuelve filas como list[dict]. Retries on lock."""
    last_err: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        conn = db()
        try:
            cur = conn.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
        except sqlite3.OperationalError as e:
            if not _is_locked_error(e) or attempt == _MAX_RETRIES - 1:
                raise
            last_err = e
            delay = _BASE_DELAY * (2 ** attempt) + random.uniform(0, 0.05)
            logger.warning("db_rows locked (attempt %d/%d), retrying in %.3fs", attempt + 1, _MAX_RETRIES, delay)
            time.sleep(delay)
        finally:
            conn.close()
    raise last_err  # type: ignore[misc]


def db_execute(sql: str, params: tuple = ()) -> None:
    """Ejecuta INSERT/UPDATE/DELETE y hace commit. Retries on lock."""
    last_err: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        conn = db()
        try:
            conn.execute(sql, params)
            conn.commit()
            return
        except sqlite3.OperationalError as e:
            if not _is_locked_error(e) or attempt == _MAX_RETRIES - 1:
                raise
            last_err = e
            delay = _BASE_DELAY * (2 ** attempt) + random.uniform(0, 0.05)
            logger.warning("db_execute locked (attempt %d/%d), retrying in %.3fs", attempt + 1, _MAX_RETRIES, delay)
            time.sleep(delay)
        finally:
            conn.close()
    raise last_err  # type: ignore[misc]


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    r = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
        (name,),
    ).fetchone()
    return bool(r)


def has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    for r in rows:
        name = r.get("name") if isinstance(r, dict) else (r[1] if len(r) > 1 else None)
        if name == column:
            return True
    return False


_SAFE_UPDATE_TABLES = frozenset({
    "invoices", "invoice_items", "customers", "products", "issuers", "users",
    "quotations", "quotation_items", "bank_movements", "bank_statements",
    "sat_cfdi", "sat_credentials", "plan_usage", "jobs", "notifications",
})

def safe_update(conn: sqlite3.Connection, table: str, row_id: int, data: dict, *, issuer_id: int | None = None) -> None:
    """Actualiza solo columnas que existan en el schema actual. Si issuer_id se pasa, añade filtro de tenant."""
    if not data:
        return
    if table not in _SAFE_UPDATE_TABLES:
        raise ValueError(f"safe_update: table '{table}' not in allowed whitelist")
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
    where = "WHERE id = ?"
    if issuer_id is not None:
        where += " AND issuer_id = ?"
        vals.append(int(issuer_id))
    conn.execute(f"UPDATE {table} SET {set_sql} {where}", vals)


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


# In-memory cache for read-only catalog data (TTL 300s)
_catalog_cache: dict[str, list[dict]] = {}
_catalog_cache_ts: dict[str, float] = {}
_CATALOG_CACHE_TTL = 300.0


def list_catalog(table: str, order_by: str | None = None) -> list[dict]:
    """Devuelve [{"key": "...", "label": "..."}] de una tabla de catálogo SAT. table debe estar en ALLOWED_CATALOG_TABLES."""
    _check_catalog_table(table)
    cache_key = f"{table}:{order_by or ''}"
    now = time.monotonic()
    if cache_key in _catalog_cache and (now - _catalog_cache_ts.get(cache_key, 0)) < _CATALOG_CACHE_TTL:
        return _catalog_cache[cache_key]
    con = db_catalogs()
    try:
        cols = _table_columns(con, table)
        key_col = _pick_column(cols, ["id", "clave", "key", "c_Clave"])
        label_col = _pick_column(cols, ["texto", "descripcion", "description", "value", "nombre"])
        ob = order_by or key_col
        rows = con.execute(
            f"SELECT {key_col} AS k, {label_col} AS v FROM {table} ORDER BY {ob}"
        ).fetchall()
        result = [{"key": str(r["k"]), "label": str(r["v"])} for r in rows]
    finally:
        con.close()
    _catalog_cache[cache_key] = result
    _catalog_cache_ts[cache_key] = now
    return result


def search_catalog(table: str, q: str, limit: int = 20) -> list[dict]:
    """Búsqueda en catálogos grandes (ProdServ, Unidad). table debe estar en ALLOWED_CATALOG_TABLES."""
    _check_catalog_table(table)
    con = db_catalogs()
    try:
        cols = _table_columns(con, table)
        key_col = _pick_column(cols, ["id", "clave", "key"])
        label_col = _pick_column(cols, ["texto", "descripcion", "description", "value", "nombre"])
        from services.db_utils import escape_like
        _q = escape_like(q)
        rows = con.execute(
            f"""
            SELECT {key_col} AS k, {label_col} AS v
            FROM {table}
            WHERE ({label_col} LIKE ? ESCAPE '\\' OR {key_col} LIKE ? ESCAPE '\\')
            LIMIT ?
            """,
            (f"%{_q}%", f"%{_q}%", int(limit)),
        ).fetchall()
        return [{"key": str(r["k"]), "label": str(r["v"])} for r in rows]
    finally:
        con.close()
