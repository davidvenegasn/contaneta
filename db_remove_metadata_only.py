"""Elimina filas de sat_cfdi que solo tienen metadata (sin xml_path)."""
import os
import sqlite3

DB_PATH = os.getenv("APP_DB_PATH", "invoicing.db")

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    cur = conn.execute("""
        SELECT COUNT(*) FROM sat_cfdi
        WHERE (xml_path IS NULL OR xml_path = '')
    """)
    n = cur.fetchone()[0]

    conn.execute("""
        DELETE FROM sat_cfdi
        WHERE xml_path IS NULL OR xml_path = ''
    """)

    conn.commit()
    conn.close()
    print(f"✅ Eliminadas {n} filas sin XML en sat_cfdi")
    print(f"   DB: {DB_PATH}")

if __name__ == "__main__":
    main()
