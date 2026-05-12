"""Audit foreign_invoices: detect totals discrepancies."""
from database import db_rows

print("=== Foreign invoices audit ===\n")

# 1. Tipo values: detect inconsistent case
tipos = db_rows("SELECT DISTINCT tipo FROM foreign_invoices")
print("Distinct tipo values:", [t["tipo"] for t in tipos])

# 2. monto_mxn null/zero
bad = db_rows(
    "SELECT issuer_id, period_month, COUNT(*) as n FROM foreign_invoices "
    "WHERE monto_mxn IS NULL OR monto_mxn = 0 GROUP BY issuer_id, period_month"
)
print(f"\nInvoices con monto_mxn nulo o cero: {len(bad)} grupos")
for r in bad:
    print(" ", dict(r))

# 3. tipo_cambio extremos
extremes = db_rows(
    "SELECT id, fecha, moneda, monto_original, tipo_cambio, monto_mxn "
    "FROM foreign_invoices WHERE tipo_cambio < 0.1 OR tipo_cambio > 50 "
    "ORDER BY tipo_cambio LIMIT 10"
)
print(f"\nInvoices con tipo_cambio raro: {len(extremes)}")
for r in extremes:
    print(" ", dict(r))

# 4. Discrepancia entre monto_original * tipo_cambio vs monto_mxn guardado
disc = db_rows("""
  SELECT id, fecha, moneda, monto_original, tipo_cambio, monto_mxn,
         ROUND(monto_original * tipo_cambio, 2) AS computed_mxn,
         ROUND(monto_mxn - (monto_original * tipo_cambio), 2) AS diff
  FROM foreign_invoices
  WHERE ABS(monto_mxn - (monto_original * tipo_cambio)) > 0.5
  LIMIT 20
""")
print(f"\nInvoices donde monto_mxn != monto_original x tipo_cambio: {len(disc)}")
for r in disc:
    print(" ", dict(r))

# 5. Para cada issuer/mes, suma desde DB vs desde Python simulando el route
audits = db_rows("""
  SELECT issuer_id, period_month, tipo, COUNT(*) n,
         SUM(monto_mxn) sql_sum, SUM(monto_original*tipo_cambio) computed_sum
  FROM foreign_invoices
  WHERE period_month IS NOT NULL
  GROUP BY issuer_id, period_month, tipo
  ORDER BY issuer_id, period_month DESC LIMIT 20
""")
print(f"\nResumen por issuer/mes/tipo:")
for r in audits:
    print(" ", dict(r))
