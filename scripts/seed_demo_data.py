#!/usr/bin/env python3
"""
Llena el usuario demo (token 'demo') con datos de prueba: clientes, productos,
proveedores, cotizaciones y facturas en sat_cfdi (emitidas y recibidas) desde
septiembre 2025 para ver el portal con información real.

Uso: python3 scripts/seed_demo_data.py

Idempotente: si ya hay datos del demo, no duplica (comprueba por issuer_id=2).
"""
import os
import secrets
import sqlite3
from random import choice, randint, uniform

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.getenv("APP_DB_PATH") or os.path.join(BASE_DIR, "invoicing.db")
DEMO_ISSUER_ID = 2  # Usuario Demo (desarrollo)
DEMO_RFC = "XAXX010101000"
DEMO_RAZON = "Usuario Demo (desarrollo)"


# --- Clientes (customer_profiles) ---
CLIENTES = [
    {"rfc": "CACX7605101P8", "legal_name": "Consultoría y Asesoría Contable SA de CV", "zip": "64000", "tax_system": "601", "email": "contabilidad@cac-sa.com", "alias": "CAC"},
    {"rfc": "GARF820315KL1", "legal_name": "Garza y Asociados Reforma", "zip": "06600", "tax_system": "626", "email": "facturacion@garza-reforma.mx", "alias": "Garza Reforma"},
    {"rfc": "TECN901201AB1", "legal_name": "Tecnología y Servicios del Norte SA", "zip": "64010", "tax_system": "601", "email": "compras@tecnorte.mx", "alias": "Tecno Norte"},
    {"rfc": "PUBL850620HH1", "legal_name": "Publicidad y Medios Digitales", "zip": "03100", "tax_system": "626", "email": "cuentas@pubmedios.com", "alias": "Pub Medios"},
    {"rfc": "DIST780115PQ2", "legal_name": "Distribuidora Regional del Pacífico", "zip": "80000", "tax_system": "601", "email": "ventas@distpacífico.mx", "alias": "Dist Pacífico"},
    {"rfc": "SERV920310LM3", "legal_name": "Servicios Integrales de Oficina", "zip": "44100", "tax_system": "626", "email": "admin@serviciosoficina.com", "alias": "Servicios Oficina"},
    {"rfc": "INVE880701CD4", "legal_name": "Inversiones y Capital de Riesgo", "zip": "06500", "tax_system": "601", "email": "operaciones@invercapital.mx", "alias": "Inver Capital"},
    {"rfc": "CONS750825EF5", "legal_name": "Construcciones y Obras Civiles SA", "zip": "44130", "tax_system": "603", "email": "proyectos@construcsa.mx", "alias": "Construc SA"},
]

# --- Productos (issuer_products): descripción, clave SAT, unidad, precio, IVA ---
PRODUCTOS = [
    {"description": "Consultoría fiscal mensual", "product_key": "80101500", "unit_key": "E48", "unit_price": 8500.00, "iva_rate": 0.16},
    {"description": "Auditoría contable", "product_key": "80101501", "unit_key": "E48", "unit_price": 15000.00, "iva_rate": 0.16},
    {"description": "Elaboración de estados financieros", "product_key": "80101502", "unit_key": "E48", "unit_price": 5200.00, "iva_rate": 0.16},
    {"description": "Asesoría en nómina", "product_key": "80101503", "unit_key": "E48", "unit_price": 3200.00, "iva_rate": 0.16},
    {"description": "Declaraciones fiscales (paquete anual)", "product_key": "80101504", "unit_key": "E48", "unit_price": 12000.00, "iva_rate": 0.16},
    {"description": "Capacitación en facturación electrónica", "product_key": "80101505", "unit_key": "H19", "unit_price": 2500.00, "iva_rate": 0.16},
    {"description": "Licencia software contable (anual)", "product_key": "85111500", "unit_key": "E48", "unit_price": 4800.00, "iva_rate": 0.16},
    {"description": "Reporte de cumplimiento SAT", "product_key": "80101506", "unit_key": "E48", "unit_price": 1800.00, "iva_rate": 0.16},
]

# --- Proveedores (supplier_profiles) ---
PROVEEDORES = [
    {"rfc": "CME970101AAA", "legal_name": "CFE Suministrador de Servicios Básicos", "zip": "01000", "tax_system": "601", "email": None, "alias": "CFE"},
    {"rfc": "TEL01234567", "legal_name": "Teléfonos de México", "zip": "01000", "tax_system": "601", "email": "facturacion@telmez.mx", "alias": "Telmex"},
    {"rfc": "OFF980101XXX", "legal_name": "Office Depot de México SA de CV", "zip": "01000", "tax_system": "601", "email": None, "alias": "Office Depot"},
    {"rfc": "AMZ990101YYY", "legal_name": "Amazon México Servicios SA de CV", "zip": "01000", "tax_system": "601", "email": "facturacion@amazon.mx", "alias": "Amazon MX"},
]

# --- Generar fechas desde 2025-09 hasta 2026-02 ---
def fechas_desde_sept_2025(cantidad_meses=6, por_mes=(3, 8)):
    out = []
    for m in range(cantidad_meses):
        year = 2025 if m < 4 else 2026
        month = 9 + m if m < 4 else (m - 3)  # 9,10,11,12,1,2
        for _ in range(randint(por_mes[0], por_mes[1])):
            day = randint(1, 28)
            hour = randint(8, 18)
            out.append(f"{year}-{month:02d}-{day:02d} {hour:02d}:00:00")
    return sorted(out)


def main():
    if load_dotenv:
        load_dotenv(os.path.join(BASE_DIR, ".env"))
    if not os.path.isfile(DB_PATH):
        print(f"DB no existe: {DB_PATH}. Arranca la app primero para crear las tablas.")
        return
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    cur = conn.execute("SELECT id FROM issuers WHERE id = ?", (DEMO_ISSUER_ID,))
    if not cur.fetchone():
        conn.close()
        print(f"No existe el usuario demo (issuer_id={DEMO_ISSUER_ID}). Ejecuta antes: python3 scripts/ensure_demo_user.py")
        return

    # Idempotencia: si ya hay facturas demo, solo agregar clientes/productos/proveedores que falten
    n_cfdi = conn.execute("SELECT COUNT(*) FROM sat_cfdi WHERE issuer_id = ?", (DEMO_ISSUER_ID,)).fetchone()[0]
    skip_cfdi_quotations = n_cfdi > 0

    # --- Customer profiles ---
    for c in CLIENTES:
        conn.execute(
            """INSERT OR IGNORE INTO customer_profiles (issuer_id, rfc, legal_name, zip, tax_system, email, alias)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (DEMO_ISSUER_ID, c["rfc"], c["legal_name"], c.get("zip") or "", c.get("tax_system") or "", c.get("email"), c.get("alias")),
        )
    print(f"  Clientes: {len(CLIENTES)} perfiles")

    # --- Issuer products ---
    for p in PRODUCTOS:
        conn.execute(
            """INSERT OR IGNORE INTO issuer_products (issuer_id, description, product_key, unit_key, unit_price, iva_rate)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (DEMO_ISSUER_ID, p["description"], p["product_key"], p.get("unit_key", "E48"), p["unit_price"], p.get("iva_rate", 0.16)),
        )
    print(f"  Productos: {len(PRODUCTOS)}")

    # --- Supplier profiles ---
    for s in PROVEEDORES:
        conn.execute(
            """INSERT OR IGNORE INTO supplier_profiles (issuer_id, rfc, legal_name, zip, tax_system, email, alias)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (DEMO_ISSUER_ID, s["rfc"], s["legal_name"], s.get("zip") or "", s.get("tax_system") or "", s.get("email"), s.get("alias")),
        )
    print(f"  Proveedores: {len(PROVEEDORES)}")

    if skip_cfdi_quotations:
        print("  Facturas y cotizaciones: ya existían, omitiendo.")
    else:
        # --- sat_cfdi: facturas emitidas (issued) desde sept 2025 ---
        fechas_emitidas = fechas_desde_sept_2025(6)
        clientes_list = CLIENTES
        for i, fecha in enumerate(fechas_emitidas):
            cliente = clientes_list[i % len(clientes_list)]
            total = round(uniform(1500, 25000), 2)
            subtotal = round(total / 1.16, 2)
            impuestos = round(total - subtotal, 2)
            uuid = f"DEMO-EMI-{2025}-{i+1:04d}-{secrets.token_hex(4).upper()}"
            conn.execute(
                """INSERT OR IGNORE INTO sat_cfdi
                   (issuer_id, direction, uuid, status, fecha_emision, rfc_emisor, nombre_emisor, rfc_receptor, nombre_receptor,
                    total, moneda, tipo_comprobante, subtotal, impuestos, serie, folio, forma_pago, metodo_pago, uso_cfdi)
                   VALUES (?, 'issued', ?, '1', ?, ?, ?, ?, ?, ?, 'MXN', 'I', ?, ?, 'A', ?, '01', 'PUE', 'G03')""",
                (DEMO_ISSUER_ID, uuid, fecha, DEMO_RFC, DEMO_RAZON, cliente["rfc"], cliente["legal_name"], total, subtotal, impuestos, str(100 + i)),
            )
        print(f"  Facturas emitidas (sat_cfdi): {len(fechas_emitidas)}")

        # --- sat_cfdi: facturas recibidas (received) desde sept 2025 ---
        fechas_recibidas = fechas_desde_sept_2025(6)
        proveedores_list = PROVEEDORES
        for i, fecha in enumerate(fechas_recibidas):
            prov = proveedores_list[i % len(proveedores_list)]
            total = round(uniform(500, 15000), 2)
            subtotal = round(total / 1.16, 2)
            impuestos = round(total - subtotal, 2)
            uuid = f"DEMO-REC-{2025}-{i+1:04d}-{secrets.token_hex(4).upper()}"
            conn.execute(
                """INSERT OR IGNORE INTO sat_cfdi
                   (issuer_id, direction, uuid, status, fecha_emision, rfc_emisor, nombre_emisor, rfc_receptor, nombre_receptor,
                    total, moneda, tipo_comprobante, subtotal, impuestos, serie, folio, forma_pago, metodo_pago, uso_cfdi)
                   VALUES (?, 'received', ?, '1', ?, ?, ?, ?, ?, ?, 'MXN', 'I', ?, ?, 'A', ?, '01', 'PUE', 'G03')""",
                (DEMO_ISSUER_ID, uuid, fecha, prov["rfc"], prov["legal_name"], DEMO_RFC, DEMO_RAZON, total, subtotal, impuestos, str(200 + i)),
            )
        print(f"  Facturas recibidas (sat_cfdi): {len(fechas_recibidas)}")

        # --- Cotizaciones (quotations + quotation_items) ---
        for i, cliente in enumerate(CLIENTES[:5]):
            folio = f"Q-2025-{1001 + i:04d}"
            public_token = secrets.token_urlsafe(24)
            status = choice(["draft", "sent", "accepted", "draft"])
            conn.execute(
                """INSERT INTO quotations (issuer_id, folio, customer_rfc, customer_legal_name, customer_email, status, public_token, iva_rate, currency, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0.16, 'MXN', ?)""",
                (DEMO_ISSUER_ID, folio, cliente["rfc"], cliente["legal_name"], cliente.get("email"), status, public_token, "Cotización de ejemplo. Vigencia 30 días."),
            )
            qid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            for j, prod in enumerate(PRODUCTOS[:3]):
                qty = randint(1, 5)
                conn.execute(
                    """INSERT INTO quotation_items (quotation_id, description, quantity, unit_price, iva_rate, sort_order)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (qid, prod["description"], qty, prod["unit_price"], prod["iva_rate"], j),
                )
        print(f"  Cotizaciones: 5 con items")

    conn.commit()
    conn.close()
    print(f"\n✅ Datos demo cargados para usuario '{DEMO_RAZON}' (issuer_id={DEMO_ISSUER_ID}).")
    print("   Entra con: http://127.0.0.1:8000/portal/home?token=demo")


if __name__ == "__main__":
    main()
