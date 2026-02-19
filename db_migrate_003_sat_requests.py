import sqlite3, os

DB_PATH = os.getenv("APP_DB_PATH", "invoicing.db")

def table_exists(conn, table):
    cur = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,))
    return cur.fetchone() is not None

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    if not table_exists(conn, "sat_requests"):
        conn.execute("""
        CREATE TABLE sat_requests (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          issuer_id INTEGER NOT NULL,
          direction TEXT NOT NULL CHECK(direction IN ('issued','received')),
          request_id TEXT NOT NULL UNIQUE,
          window_from TEXT NOT NULL,
          window_to TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'queued'
            CHECK(status IN ('queued','verifying','finished','error')),
          tries INTEGER NOT NULL DEFAULT 0,
          last_error TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
        );
        """)
        conn.execute("CREATE INDEX idx_sat_requests_status ON sat_requests(status);")
        conn.execute("CREATE INDEX idx_sat_requests_issuer ON sat_requests(issuer_id, direction, status);")

    conn.commit()
    conn.close()
    print("✅ Migración 003 OK (sat_requests)")

if __name__ == "__main__":
    main()