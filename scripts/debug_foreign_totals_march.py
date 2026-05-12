from database import db_rows
ISSUER_ID = 11  # cambiar si fuera otro
YM = '2026-03'

print(f"=== Audit foreign_invoices issuer={ISSUER_ID} ym={YM} ===\n")

# 1. Todos los rows del periodo
rows = db_rows("""
    SELECT id, fecha, tipo, moneda, monto_original, tipo_cambio, monto_mxn, period_month, empresa
    FROM foreign_invoices
    WHERE issuer_id = ? AND period_month = ?
    ORDER BY fecha DESC
""", (ISSUER_ID, YM))
print(f"Total rows en period_month='{YM}': {len(rows)}")
for r in rows:
    print(f"  id={r['id']} fecha={r['fecha']} tipo={r['tipo']!r} {r['moneda']} {r['monto_original']} × {r['tipo_cambio']} = {r['monto_mxn']} | {r['empresa']}")

# 2. Distinct tipo values
tipos = db_rows("SELECT DISTINCT tipo, COUNT(*) AS n FROM foreign_invoices WHERE issuer_id = ? AND period_month = ? GROUP BY tipo", (ISSUER_ID, YM))
print(f"\nTipos distintos: {[dict(t) for t in tipos]}")

# 3. SQL sum (independiente del Python)
r = db_rows("SELECT SUM(monto_mxn) AS s_mxn, SUM(monto_original) AS s_orig, COUNT(*) AS n FROM foreign_invoices WHERE issuer_id = ? AND period_month = ? AND UPPER(TRIM(COALESCE(tipo,''))) = 'GASTO'", (ISSUER_ID, YM))
print(f"\nSQL sum (UPPER+TRIM tipo='GASTO'): {dict(r[0])}")
r2 = db_rows("SELECT SUM(monto_mxn) AS s_mxn, COUNT(*) AS n FROM foreign_invoices WHERE issuer_id = ? AND period_month = ? AND tipo = 'GASTO'", (ISSUER_ID, YM))
print(f"SQL sum (exact tipo='GASTO'): {dict(r2[0])}")

# 4. Python sum (replica el route)
items = db_rows("SELECT * FROM foreign_invoices WHERE issuer_id = ? AND period_month = ? ORDER BY fecha DESC, id DESC LIMIT 200", (ISSUER_ID, YM))
sum_gastos_py = sum(r.get("monto_mxn", 0) or 0 for r in items if (r.get("tipo") or "") == "GASTO")
sum_ingresos_py = sum(r.get("monto_mxn", 0) or 0 for r in items if (r.get("tipo") or "") == "INGRESO")
print(f"\nPython sum (replica route): gastos={sum_gastos_py:.2f} ingresos={sum_ingresos_py:.2f}")

# 5. Detecta nulos y ceros
nulos = [r for r in items if r.get("monto_mxn") is None]
ceros = [r for r in items if r.get("monto_mxn") == 0]
print(f"\nInvoices con monto_mxn NULL: {len(nulos)} | con 0: {len(ceros)}")
