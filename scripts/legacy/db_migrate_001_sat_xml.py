# --- OBSOLETO ---
# Script deprecado. La fuente de verdad es migrations/ + migrations_runner.py.
# Ver MIGRATION_LEGACY_MAP.md en la raíz del proyecto. No ejecutar.
# ---

import sqlite3
import os

DB_PATH = os.getenv("APP_DB_PATH", "invoicing.db")

def column_exists(conn, table, col):
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())

def table_exists(conn, table):
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,)
    )
    return cur.fetchone() is not None

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # 1) sat_cfdi: columnas para tracking de XML y parsing
    if not column_exists(conn, "sat_cfdi", "xml_sha256"):
        conn.execute("ALTER TABLE sat_cfdi ADD COLUMN xml_sha256 TEXT;")

    if not column_exists(conn, "sat_cfdi", "xml_downloaded_at"):
        conn.execute("ALTER TABLE sat_cfdi ADD COLUMN xml_downloaded_at TEXT;")

    if not column_exists(conn, "sat_cfdi", "parsed_at"):
        conn.execute("ALTER TABLE sat_cfdi ADD COLUMN parsed_at TEXT;")

    if not column_exists(conn, "sat_cfdi", "parse_version"):
        conn.execute("ALTER TABLE sat_cfdi ADD COLUMN parse_version INTEGER;")

    # 2) sat_jobs: tabla para cola/estado de sincronizaciones (SaaS-friendly)
    if not table_exists(conn, "sat_jobs"):
        conn.execute("""
        CREATE TABLE sat_jobs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          issuer_id INTEGER NOT NULL,
          job_type TEXT NOT NULL CHECK(job_type IN ('metadata','xml','parse')),
          direction TEXT CHECK(direction IN ('issued','received')),
          window_from TEXT,
          window_to TEXT,
          status TEXT NOT NULL DEFAULT 'queued'
            CHECK(status IN ('queued','running','ok','error')),
          attempts INTEGER NOT NULL DEFAULT 0,
          locked_at TEXT,
          started_at TEXT,
          finished_at TEXT,
          last_error TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
        );
        """)

        conn.execute("CREATE INDEX idx_sat_jobs_status ON sat_jobs(status);")
        conn.execute("CREATE INDEX idx_sat_jobs_issuer ON sat_jobs(issuer_id, job_type, status);")

    conn.commit()
    conn.close()
    print(f"✅ Migración 001 OK en DB: {DB_PATH}")

if __name__ == "__main__":
    main()
