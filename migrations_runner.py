"""
Sistema simple de migraciones SQLite.
Aplica archivos migrations/*.sql ordenados por prefijo numérico (001_, 002_, ...).
Conexiones con timeout y pragmas para reducir disk I/O y locks (WAL, busy_timeout, foreign_keys).
"""
import logging
import os
import re
import sqlite3

logger = logging.getLogger(__name__)

# Timeout en segundos para esperar lock de la DB (evitar "database is locked" inmediato)
SQLITE_TIMEOUT = 30
# Milisegundos que SQLite espera en PRAGMA busy_timeout antes de fallar
SQLITE_BUSY_MS = 5000

_SCHEMA_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT
);
"""

# Directorio por defecto: migrations/ junto a este módulo (raíz del proyecto)
_RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MIGRATIONS_DIR = os.path.join(_RUNNER_DIR, "migrations")

# Patrón: prefijo numérico opcional + _ + nombre (ej. 001_crear_tabla.sql, 002_add_column.sql)
_MIGRATION_PATTERN = re.compile(r"^(\d+)_(.+)\.sql$", re.IGNORECASE)


def _apply_sqlite_pragmas(conn: sqlite3.Connection) -> None:
    """Aplica pragmas para reducir I/O y locks. Seguro para migraciones y app."""
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = %d;" % SQLITE_BUSY_MS)
    # WAL mejora concurrencia lectura/escritura; genera .db-wal y .db-shm (ver MIGRATIONS.md si se dañan)
    conn.execute("PRAGMA journal_mode = WAL;")


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_TABLE.strip())


def _get_applied_versions(conn: sqlite3.Connection) -> set[str]:
    cur = conn.execute("SELECT version FROM schema_migrations")
    return {row[0] for row in cur.fetchall()}


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Verifica si una columna existe en una tabla usando PRAGMA table_info."""
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def _safe_add_column(
    conn: sqlite3.Connection, table: str, column: str, column_type: str
) -> bool:
    """
    Agrega una columna a una tabla si no existe. Idempotente.
    Returns: True si se agregó, False si ya existía.
    """
    if _column_exists(conn, table, column):
        logger.debug("Column %s.%s already exists, skipping.", table, column)
        return False
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type};")
        logger.debug("Added column %s.%s", table, column)
        return True
    except sqlite3.OperationalError as e:
        # Si falla por "duplicate column name", ignorar (idempotente)
        if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
            logger.debug("Column %s.%s already exists (caught exception), skipping.", table, column)
            return False
        # Otros errores se re-lanzan
        raise


def _apply_003_safe_add_columns(conn: sqlite3.Connection) -> None:
    """
    Aplica la migración 003: asegura columnas críticas que causan crash si faltan.
    Usa _safe_add_column para ser idempotente.
    """
    # sat_cfdi: columnas críticas que causan crash si faltan
    sat_cfdi_columns = [
        ("serie", "TEXT"),
        ("folio", "TEXT"),
        ("forma_pago", "TEXT"),
        ("metodo_pago", "TEXT"),
        ("uso_cfdi", "TEXT"),
        ("subtotal", "REAL"),
        ("descuento", "REAL"),
        ("impuestos", "REAL"),
        ("concepto", "TEXT"),
        ("retenciones", "REAL"),
        ("tipo_comprobante", "TEXT"),
        ("xml_status", "TEXT"),
    ]
    
    added_count = 0
    for col, col_type in sat_cfdi_columns:
        if _safe_add_column(conn, "sat_cfdi", col, col_type):
            added_count += 1
    
    if added_count > 0:
        logger.info("  Added %d column(s) to sat_cfdi", added_count)
    
    # invoices: columna crítica que causa crash si falta
    if _safe_add_column(conn, "invoices", "issue_date", "TEXT"):
        logger.info("  Added issue_date to invoices")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Verifica si una tabla existe."""
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,)
    )
    return cur.fetchone() is not None


def _apply_004_optional_columns_and_constraints(conn: sqlite3.Connection) -> None:
    """
    Aplica la migración 004: columnas opcionales (invoices, invoice_items),
    constraint customer_profiles (zip/tax_system nullable) e índices mínimos.
    Idempotente y reintentable.
    """
    # Limpiar tabla temporal si quedó de un intento anterior
    conn.execute("DROP TABLE IF EXISTS customer_profiles_new")

    # A) invoices: columnas recomendadas (ALTA, no-crash)
    if _table_exists(conn, "invoices"):
        invoices_columns = [
            ("export_code", "TEXT"),
            ("tipo_comprobante", "TEXT"),
            ("series", "TEXT"),
            ("folio_number", "TEXT"),
            ("order_ref", "TEXT"),
            ("notes", "TEXT"),
            ("status", "TEXT"),
            ("cancelled", "INTEGER DEFAULT 0"),
        ]
        n = sum(1 for col, typ in invoices_columns if _safe_add_column(conn, "invoices", col, typ))
        if n > 0:
            logger.info("  Added %d column(s) to invoices", n)

    # B) invoice_items: columnas opcionales
    if _table_exists(conn, "invoice_items"):
        for col, typ in [("unit_key", "TEXT"), ("discount", "REAL")]:
            _safe_add_column(conn, "invoice_items", col, typ)

    # C) customer_profiles: asegurar zip y tax_system nullable (rebuild si hace falta)
    if _table_exists(conn, "customer_profiles"):
        cur = conn.execute("PRAGMA table_info(customer_profiles)")
        rows = cur.fetchall()
        # row: (cid, name, type, notnull, dflt_value, pk)
        col_info = {row[1]: row[3] for row in rows}  # name -> notnull
        need_rebuild = col_info.get("zip", 0) == 1 or col_info.get("tax_system", 0) == 1
        if need_rebuild:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("""
                CREATE TABLE customer_profiles_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    issuer_id INTEGER NOT NULL,
                    rfc TEXT NOT NULL,
                    legal_name TEXT NOT NULL,
                    zip TEXT,
                    tax_system TEXT,
                    email TEXT,
                    alias TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(issuer_id, rfc),
                    FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
                )
            """)
            conn.execute("""
                INSERT INTO customer_profiles_new
                (id, issuer_id, rfc, legal_name, zip, tax_system, email, alias, created_at, updated_at)
                SELECT id, issuer_id, rfc, legal_name, zip, tax_system, email, alias, created_at, updated_at
                FROM customer_profiles
            """)
            conn.execute("DROP TABLE customer_profiles")
            conn.execute("ALTER TABLE customer_profiles_new RENAME TO customer_profiles")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_customer_profiles_issuer_id ON customer_profiles(issuer_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_customer_profiles_alias ON customer_profiles(alias)")
            conn.execute("PRAGMA foreign_keys = ON")
            logger.info("  Rebuilt customer_profiles (zip/tax_system nullable)")

    # D) Índices mínimos (IF NOT EXISTS es idempotente; solo si existe la tabla)
    if _table_exists(conn, "invoices"):
        for sql in [
            "CREATE INDEX IF NOT EXISTS idx_invoices_issuer_uuid ON invoices(issuer_id, uuid)",
            "CREATE INDEX IF NOT EXISTS idx_invoices_issuer_payment_method ON invoices(issuer_id, payment_method)",
            "CREATE INDEX IF NOT EXISTS idx_invoices_issuer_issue_date ON invoices(issuer_id, issue_date)",
        ]:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError as e:
                if "duplicate" not in str(e).lower() and "already exists" not in str(e).lower():
                    raise


def _list_migration_files(migrations_dir: str) -> list[tuple[str, str]]:
    """
    Lista archivos *.sql en migrations_dir ordenados por prefijo numérico.
    Returns: list of (version_key, full_path), e.g. [("001", "/path/migrations/001_foo.sql"), ...]
    """
    if not os.path.isdir(migrations_dir):
        return []
    out: list[tuple[str, str]] = []
    for name in os.listdir(migrations_dir):
        m = _MIGRATION_PATTERN.match(name)
        if m:
            num, _ = m.groups()
            path = os.path.join(migrations_dir, name)
            if os.path.isfile(path):
                out.append((num, path))
    out.sort(key=lambda x: (int(x[0]), x[1]))
    return out


def apply_migrations(
    db_path: str,
    migrations_dir: str | None = None,
) -> None:
    """
    Aplica migraciones pendientes a la base SQLite en db_path.
    - Crea la DB si no existe (sqlite3.connect la crea).
    - Crea la tabla schema_migrations si no existe.
    - Aplica cada migrations/*.sql (ordenado por prefijo 001_, 002_, ...) en una transacción.
    - Inserta en schema_migrations al aplicar cada una.
    - Idempotente: si una versión ya está aplicada, la salta.
    """
    migrations_dir = migrations_dir or DEFAULT_MIGRATIONS_DIR
    # Crear directorio de migraciones si no existe (no crea la DB; la DB se crea al conectar)
    os.makedirs(migrations_dir, exist_ok=True)

    conn = sqlite3.connect(db_path, timeout=SQLITE_TIMEOUT)
    conn.row_factory = sqlite3.Row
    _apply_sqlite_pragmas(conn)
    try:
        _ensure_migrations_table(conn)
        applied = _get_applied_versions(conn)
        candidates = _list_migration_files(migrations_dir)

        for version_key, filepath in candidates:
            # version_key es el prefijo numérico (001, 002, ...); lo usamos como version en schema_migrations
            version = version_key
            if version in applied:
                logger.info("Skipping %s (already applied).", version)
                continue

            with open(filepath, "r", encoding="utf-8") as f:
                sql = f.read()

            logger.info("Applying %s…", version)
            try:
                # BEGIN IMMEDIATE adquiere lock de escritura de inmediato, evita carreras con otras conexiones
                conn.execute("BEGIN IMMEDIATE")
                
                # Migraciones con lógica Python (idempotente)
                if version == "003":
                    _apply_003_safe_add_columns(conn)
                elif version == "004":
                    _apply_004_optional_columns_and_constraints(conn)
                else:
                    # Migraciones normales: ejecutar SQL directamente
                    conn.executescript(sql)
                
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, datetime('now'))",
                    (version,),
                )
                conn.commit()
                logger.info("Applying %s… done.", version)
            except Exception as e:
                conn.rollback()
                logger.exception("Applying %s failed: %s", version, e)
                raise
    finally:
        conn.close()
