import sqlite3
import os

DB_PATH = os.getenv("APP_DB_PATH", "invoicing.db")

def column_exists(conn, table, col):
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Campos adicionales del CFDI extraídos del XML
    fields = [
        ("serie", "TEXT"),
        ("folio", "TEXT"),
        ("forma_pago", "TEXT"),
        ("metodo_pago", "TEXT"),  # PUE/PPD
        ("uso_cfdi", "TEXT"),
        ("subtotal", "REAL"),
        ("descuento", "REAL"),
        ("impuestos", "REAL"),
        ("lugar_expedicion", "TEXT"),
        ("condiciones_pago", "TEXT"),
        ("xml_status", "TEXT"),  # pending, downloaded, parsed, error
    ]

    for field_name, field_type in fields:
        if not column_exists(conn, "sat_cfdi", field_name):
            conn.execute(f"ALTER TABLE sat_cfdi ADD COLUMN {field_name} {field_type};")
            print(f"  ✅ Agregada columna: {field_name}")

    # Índices para búsquedas comunes
    indexes = [
        ("idx_sat_cfdi_xml_status", "sat_cfdi(xml_status)"),
        ("idx_sat_cfdi_serie_folio", "sat_cfdi(serie, folio)"),
        ("idx_sat_cfdi_metodo_pago", "sat_cfdi(metodo_pago)"),
    ]

    for idx_name, idx_def in indexes:
        try:
            conn.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_def};")
            print(f"  ✅ Índice creado: {idx_name}")
        except sqlite3.OperationalError as e:
            if "already exists" not in str(e).lower():
                print(f"  ⚠️  Error creando índice {idx_name}: {e}")

    conn.commit()
    conn.close()
    print(f"✅ Migración 004 OK (campos CFDI adicionales) en DB: {DB_PATH}")

if __name__ == "__main__":
    main()
