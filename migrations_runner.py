"""
Sistema simple de migraciones SQLite.
Aplica archivos migrations/*.sql ordenados por prefijo numérico (001_, 002_, ...).
Conexiones con timeout y pragmas para reducir disk I/O y locks (WAL, busy_timeout, foreign_keys).
"""
import hashlib
import logging
import os
import re
import sqlite3
import time

from services.errors import AppError

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


def _apply_008_users_active(conn: sqlite3.Connection) -> None:
    """Aplica 008: columna users.active (default 1) para login solo usuarios activos."""
    if _table_exists(conn, "users"):
        _safe_add_column(conn, "users", "active", "INTEGER NOT NULL DEFAULT 1")


def _apply_014_sat_credentials_validation(conn: sqlite3.Connection) -> None:
    """Aplica 014: columnas validation_at, validation_ok, validation_message en sat_credentials (self-serve FIEL)."""
    if not _table_exists(conn, "sat_credentials"):
        return
    for col, col_type in [
        ("validation_at", "TEXT"),
        ("validation_ok", "INTEGER"),
        ("validation_message", "TEXT"),
    ]:
        _safe_add_column(conn, "sat_credentials", col, col_type)


def _apply_021_bank_movements_module(conn: sqlite3.Connection) -> None:
    """
    Módulo Movimientos: columnas para validación RFC/periodo, conciliación con CFDI.
    Extiende bank_statements y bank_movements; crea bank_invoice_matches.
    Idempotente (_safe_add_column + CREATE TABLE IF NOT EXISTS).
    """
    # bank_statements: columnas para validación y periodo
    if _table_exists(conn, "bank_statements"):
        for col, col_type in [
            ("source_file_name", "TEXT"),
            ("parser_name", "TEXT"),
            ("parser_version", "TEXT"),
            ("detected_holder_name", "TEXT"),
            ("detected_holder_rfc", "TEXT"),
            ("detected_account_last4", "TEXT"),
            ("period_month", "TEXT"),
            ("statement_year", "INTEGER"),
            ("statement_month", "INTEGER"),
            ("opening_balance", "REAL"),
            ("closing_balance", "REAL"),
            ("currency", "TEXT"),
            ("status", "TEXT"),
            ("rejection_reason", "TEXT"),
            ("total_movements", "INTEGER"),
            ("bank_account_id", "INTEGER"),
            ("updated_at", "TEXT"),
        ]:
            _safe_add_column(conn, "bank_statements", col, col_type)
    # bank_movements: columnas para conciliación y clasificación
    if _table_exists(conn, "bank_movements"):
        for col, col_type in [
            ("bank_statement_id", "INTEGER"),
            ("bank_account_id", "INTEGER"),
            ("period_month", "TEXT"),
            ("movement_index", "INTEGER"),
            ("raw_description", "TEXT"),
            ("normalized_description", "TEXT"),
            ("amount", "REAL"),
            ("direction", "TEXT"),
            ("reference_text", "TEXT"),
            ("counterparty_name_detected", "TEXT"),
            ("counterparty_rfc_detected", "TEXT"),
            ("movement_type", "TEXT"),
            ("business_effect", "TEXT"),
            ("tax_effect", "TEXT"),
            ("requires_cfdi", "INTEGER"),
            ("cfdi_match_status", "TEXT"),
            ("review_status", "TEXT"),
            ("duplicate_hash", "TEXT"),
            ("is_possible_duplicate", "INTEGER"),
            ("updated_at", "TEXT"),
        ]:
            _safe_add_column(conn, "bank_movements", col, col_type)
    # Tabla sugerencias/confirmaciones movimiento ↔ CFDI
    if not _table_exists(conn, "bank_invoice_matches"):
        conn.execute("""
            CREATE TABLE bank_invoice_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issuer_id INTEGER NOT NULL,
                bank_movement_id INTEGER NOT NULL,
                cfdi_id INTEGER NOT NULL,
                match_role TEXT NOT NULL,
                score INTEGER NOT NULL,
                score_breakdown_json TEXT,
                matched_amount REAL,
                status TEXT NOT NULL DEFAULT 'suggested',
                is_partial INTEGER DEFAULT 0,
                created_by TEXT DEFAULT 'system',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE,
                FOREIGN KEY (bank_movement_id) REFERENCES bank_movements(id) ON DELETE CASCADE,
                FOREIGN KEY (cfdi_id) REFERENCES sat_cfdi(id) ON DELETE CASCADE
            )
        """)
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_bim_movement ON bank_invoice_matches(bank_movement_id)",
            "CREATE INDEX IF NOT EXISTS idx_bim_cfdi ON bank_invoice_matches(cfdi_id)",
            "CREATE INDEX IF NOT EXISTS idx_bim_status ON bank_invoice_matches(status)",
            "CREATE INDEX IF NOT EXISTS idx_bim_issuer ON bank_invoice_matches(issuer_id)",
        ]:
            conn.execute(idx_sql)
        logger.info("  Created table bank_invoice_matches")


def _apply_011_audit_log_columns(conn: sqlite3.Connection) -> None:
    """Aplica 011: columnas entity, entity_id, meta_json, ip, user_agent en audit_log."""
    if not _table_exists(conn, "audit_log"):
        return
    for col, typ in [
        ("entity", "TEXT"),
        ("entity_id", "TEXT"),
        ("meta_json", "TEXT"),
        ("ip", "TEXT"),
        ("user_agent", "TEXT"),
    ]:
        _safe_add_column(conn, "audit_log", col, typ)


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


def _movement_dedup_hash(issuer_id: int, fecha: str, descripcion: str, deposito, retiro) -> str:
    """Misma fórmula que portal/ingest para dedupe de movimientos."""
    dep = "" if deposito is None else f"{float(deposito):.2f}"
    ret = "" if retiro is None else f"{float(retiro):.2f}"
    desc = (descripcion or "").strip()[:500].replace("\r", " ").replace("\n", " ")
    payload = f"{issuer_id}|{fecha or ''}|{desc}|{dep}|{ret}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _apply_023_bank_movements_dedup(conn: sqlite3.Connection) -> None:
    """
    Añade movement_hash a bank_movements, rellena hashes en filas existentes,
    elimina duplicados (conserva uno por issuer_id + movement_hash) y crea índice único.
    """
    if not _table_exists(conn, "bank_movements"):
        logger.debug("bank_movements no existe, omitiendo 023")
        return
    _safe_add_column(conn, "bank_movements", "movement_hash", "TEXT")
    cur = conn.execute(
        "SELECT id, issuer_id, fecha, descripcion, deposito, retiro FROM bank_movements WHERE movement_hash IS NULL"
    )
    rows = cur.fetchall()
    for row in rows:
        row_id = row["id"]
        issuer_id = row["issuer_id"]
        fecha = row["fecha"] or ""
        descripcion = row["descripcion"] or ""
        deposito = row["deposito"]
        retiro = row["retiro"]
        m_hash = _movement_dedup_hash(issuer_id, fecha, descripcion, deposito, retiro)
        conn.execute("UPDATE bank_movements SET movement_hash = ? WHERE id = ?", (m_hash, row_id))
    if rows:
        logger.info("023: backfill movement_hash en %d filas", len(rows))
    # Borrar duplicados: conservar el de menor id por (issuer_id, movement_hash)
    cur = conn.execute(
        """
        DELETE FROM bank_movements WHERE movement_hash IS NOT NULL AND id NOT IN (
            SELECT MIN(id) FROM bank_movements WHERE movement_hash IS NOT NULL GROUP BY issuer_id, movement_hash
        )
        """
    )
    deleted = cur.rowcount
    if deleted:
        logger.info("023: eliminados %d movimientos duplicados", deleted)
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_bank_movements_issuer_hash ON bank_movements(issuer_id, movement_hash) WHERE movement_hash IS NOT NULL"
        )
    except sqlite3.OperationalError as e:
        if "already exists" not in str(e).lower():
            logger.warning("023: índice único movement_hash: %s", e)


def _apply_025_jobs_robust(conn: sqlite3.Connection) -> None:
    """
    Sistema robusto de jobs:
    - attempts/max_attempts + run_after para reintentos
    - locked_by/locked_at con lease para evitar doble ejecución
    - payload_hash + índice parcial único para dedupe (queued/running)
    - error_json para fallo estructurado
    """
    if not _table_exists(conn, "jobs"):
        return

    # Columnas nuevas (idempotente)
    for col, typ in [
        ("attempts", "INTEGER NOT NULL DEFAULT 0"),
        ("max_attempts", "INTEGER NOT NULL DEFAULT 3"),
        ("run_after", "TEXT"),
        ("locked_by", "TEXT"),
        ("locked_at", "TEXT"),
        ("payload_hash", "TEXT"),
        ("error_json", "TEXT"),
    ]:
        _safe_add_column(conn, "jobs", col, typ)

    # Backfill payload_hash si hay jobs existentes sin hash.
    try:
        cur = conn.execute("SELECT id, issuer_id, name, payload_json FROM jobs WHERE payload_hash IS NULL")
        rows = cur.fetchall()
        for r in rows:
            jid = r["id"]
            issuer_id = r["issuer_id"]
            name = (r["name"] or "").strip()
            payload_json = (r["payload_json"] or "").strip()
            h = hashlib.sha256(f"{issuer_id}|{name}|{payload_json}".encode("utf-8")).hexdigest()
            conn.execute("UPDATE jobs SET payload_hash = ? WHERE id = ?", (h, jid))
        if rows:
            logger.info("025: backfill payload_hash en %d jobs", len(rows))
    except Exception as e:
        logger.warning("025: no se pudo backfill payload_hash: %s", e)

    # Dedupe: conservar el job más antiguo por (issuer_id,name,payload_hash) en estados activos.
    try:
        cur = conn.execute(
            """
            DELETE FROM jobs
            WHERE status IN ('queued','running')
              AND payload_hash IS NOT NULL
              AND id NOT IN (
                SELECT MIN(id)
                FROM jobs
                WHERE status IN ('queued','running') AND payload_hash IS NOT NULL
                GROUP BY issuer_id, name, payload_hash
              )
            """
        )
        deleted = cur.rowcount
        if deleted:
            logger.info("025: eliminados %d jobs duplicados (queued/running)", deleted)
    except Exception as e:
        logger.warning("025: dedupe jobs falló: %s", e)

    # Índices recomendados (IF NOT EXISTS = idempotente)
    for sql in [
        "CREATE INDEX IF NOT EXISTS idx_jobs_status_run_after ON jobs(status, run_after)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_issuer_status ON jobs(issuer_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_locked_at ON jobs(locked_at)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_payload_hash ON jobs(payload_hash)",
    ]:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError as e:
            if "already exists" not in str(e).lower():
                raise

    # Índice único parcial para dedupe (evita duplicados por issuer+name+payload en cola/ejecución).
    # Nota: puede fallar si aún quedan duplicados; por eso hacemos dedupe antes.
    try:
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_dedupe_active
            ON jobs(issuer_id, name, payload_hash)
            WHERE payload_hash IS NOT NULL AND status IN ('queued','running')
            """
        )
    except sqlite3.OperationalError as e:
        # Si hay conflictos, no romper migraciones; se puede limpiar manualmente y recrear.
        logger.warning("025: no se pudo crear idx_jobs_dedupe_active: %s", e)


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

    # Reintentos ante locks (dos procesos arrancando a la vez).
    # Nota: usamos una transacción global (BEGIN IMMEDIATE) para evitar carreras:
    # si 2 procesos arrancan, el segundo espera/reintenta y al entrar ya ve versiones aplicadas.
    last_exc: Exception | None = None
    for attempt in range(3):
        conn = sqlite3.connect(db_path, timeout=SQLITE_TIMEOUT)
        conn.row_factory = sqlite3.Row
        _apply_sqlite_pragmas(conn)
        try:
            _ensure_migrations_table(conn)
            candidates = _list_migration_files(migrations_dir)

            try:
                conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as e:
                # "database is locked" / "database schema is locked"
                msg = str(e).lower()
                if "locked" in msg and attempt < 2:
                    conn.close()
                    time.sleep(1 + attempt)  # 1s, 2s
                    last_exc = e
                    continue
                raise AppError(
                    code="MIGRATION_LOCKED",
                    public_message="La base de datos está ocupada. Intenta de nuevo en unos segundos.",
                    internal_message=f"BEGIN IMMEDIATE failed: {e}",
                    status_code=500,
                )

            applied = _get_applied_versions(conn)
            for version_key, filepath in candidates:
                version = version_key
                filename = os.path.basename(filepath)
                if version in applied:
                    logger.info("Skipping migration %s (already applied).", filename)
                    continue

                start = time.time()
                logger.info("Applying migration %s", filename)
                try:
                    # Migraciones con lógica Python (idempotente)
                    if version == "003":
                        _apply_003_safe_add_columns(conn)
                    elif version == "004":
                        _apply_004_optional_columns_and_constraints(conn)
                    elif version == "006":
                        _safe_add_column(conn, "users", "name", "TEXT")
                    elif version == "008":
                        _apply_008_users_active(conn)
                    elif version == "011":
                        _apply_011_audit_log_columns(conn)
                    elif version == "014":
                        _apply_014_sat_credentials_validation(conn)
                    elif version == "016":
                        _safe_add_column(conn, "issuers", "trial_expires_at", "TEXT")
                    elif version == "021":
                        _apply_021_bank_movements_module(conn)
                    elif version == "023":
                        _apply_023_bank_movements_dedup(conn)
                    elif version == "025":
                        _apply_025_jobs_robust(conn)
                    elif version == "033":
                        _safe_add_column(conn, "users", "password_changed_at", "TEXT")
                    else:
                        with open(filepath, "r", encoding="utf-8") as f:
                            sql = f.read()
                        conn.executescript(sql)

                    conn.execute(
                        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, datetime('now'))",
                        (version,),
                    )
                    applied.add(version)
                    ms = int((time.time() - start) * 1000)
                    logger.info("Applied %s in %dms", filename, ms)
                except Exception as e:
                    conn.rollback()
                    logger.exception("Migration failed (%s): %s", filename, e)
                    raise AppError(
                        code="MIGRATION_FAILED",
                        public_message="Error actualizando base de datos",
                        internal_message=f"Migration {filename} failed: {e}",
                        status_code=500,
                    )

            conn.commit()
            return
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # Fallback (no debería llegar aquí)
    raise AppError(
        code="MIGRATION_LOCKED",
        public_message="La base de datos está ocupada. Intenta de nuevo en unos segundos.",
        internal_message=f"Migration retries exhausted: {last_exc}",
        status_code=500,
    )
