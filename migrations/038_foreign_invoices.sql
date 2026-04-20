-- foreign_invoices: invoices/gastos de servicios internacionales
CREATE TABLE IF NOT EXISTS foreign_invoices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  tipo TEXT NOT NULL CHECK(tipo IN ('INGRESO','GASTO')),
  fecha TEXT NOT NULL,
  invoice_number TEXT NOT NULL,
  empresa TEXT NOT NULL,
  pais TEXT,
  tax_id TEXT,
  descripcion TEXT NOT NULL,
  moneda TEXT NOT NULL DEFAULT 'USD',
  monto_original REAL NOT NULL,
  tipo_cambio REAL NOT NULL,
  monto_mxn REAL NOT NULL,
  forma_pago TEXT,
  referencia_pago TEXT,
  archivo TEXT,
  notas TEXT,
  period_month TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_foreign_invoices_issuer ON foreign_invoices(issuer_id);
CREATE INDEX IF NOT EXISTS idx_foreign_invoices_period ON foreign_invoices(issuer_id, period_month);
