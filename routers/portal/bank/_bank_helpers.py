"""Bank-specific shared helpers and constants used across bank sub-modules."""
import hashlib
from typing import Optional

from database import has_column

# Constants
MAX_BANK_PDF_SIZE = 15 * 1024 * 1024  # 15MB
MAX_BANK_PDF_FILES = 10
MAX_BANK_PDF_TOTAL_SIZE = 50 * 1024 * 1024  # 50MB total multi-upload


def ensure_bank_exports_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bank_pdf_exports (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          issuer_id INTEGER NOT NULL,
          file_id TEXT NOT NULL,
          pdf_path TEXT NOT NULL,
          xlsx_path TEXT NOT NULL,
          meta_json TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          UNIQUE(issuer_id, file_id)
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_pdf_exports_issuer ON bank_pdf_exports(issuer_id, created_at);")


def ensure_bank_statements_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bank_statements (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          issuer_id INTEGER NOT NULL,
          bank_name TEXT,
          account_last4 TEXT,
          period_start TEXT,
          period_end TEXT,
          source_pdf_path TEXT NOT NULL,
          source_pdf_sha256 TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_bank_statements_issuer_sha ON bank_statements(issuer_id, source_pdf_sha256);")


def movement_dedup_hash(issuer_id: int, fecha: str, descripcion: str, deposito: Optional[float], retiro: Optional[float]) -> str:
    """Hash para deduplicar movimientos: mismo issuer + fecha + concepto + montos = mismo movimiento."""
    dep = f"{float(deposito or 0):.2f}"
    ret = f"{float(retiro or 0):.2f}"
    desc = (descripcion or "").strip()[:500].replace("\r", " ").replace("\n", " ")
    payload = f"{issuer_id}|{fecha or ''}|{desc}|{dep}|{ret}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ensure_bank_movements_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bank_movements (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          issuer_id INTEGER NOT NULL,
          statement_file_id TEXT NOT NULL DEFAULT '0',
          movement_hash TEXT,
          fecha TEXT,
          descripcion TEXT,
          raw_description TEXT,
          normalized_description TEXT,
          deposito REAL,
          retiro REAL,
          saldo REAL,
          tipo TEXT,
          categoria TEXT,
          metodo_hint TEXT,
          contraparte_hint TEXT,
          reference_text TEXT,
          rfc_encontrado TEXT,
          confidence_score INTEGER,
          source_page_first INTEGER,
          period_month TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    # Add columns that may be missing in older databases
    for col, coltype in [
        ("movement_hash", "TEXT"),
        ("raw_description", "TEXT"),
        ("normalized_description", "TEXT"),
        ("reference_text", "TEXT"),
        ("period_month", "TEXT"),
    ]:
        if not has_column(conn, "bank_movements", col):
            try:
                conn.execute(f"ALTER TABLE bank_movements ADD COLUMN {col} {coltype};")
            except Exception:
                pass
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_movements_issuer_statement ON bank_movements(issuer_id, statement_file_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_movements_issuer_tipo ON bank_movements(issuer_id, tipo);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_movements_issuer_categoria ON bank_movements(issuer_id, categoria);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_movements_issuer_fecha ON bank_movements(issuer_id, fecha);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_movements_issuer_confidence ON bank_movements(issuer_id, confidence_score);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_movements_issuer_period ON bank_movements(issuer_id, period_month);")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_bank_movements_issuer_hash ON bank_movements(issuer_id, movement_hash) WHERE movement_hash IS NOT NULL;")
