import sqlite3
import os

DB_PATH = os.getenv("APP_DB_PATH", "invoicing.db")

def column_exists(conn, table, col):
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    if not column_exists(conn, "sat_cfdi", "xml_path"):
        conn.execute("ALTER TABLE sat_cfdi ADD COLUMN xml_path TEXT;")

    conn.commit()
    conn.close()
    print(f"✅ Migración 002 OK (xml_path) en DB: {DB_PATH}")

if __name__ == "__main__":
    main()