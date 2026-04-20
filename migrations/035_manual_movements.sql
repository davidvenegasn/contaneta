-- manual_movements: movimientos manuales capturados por el usuario
CREATE TABLE IF NOT EXISTS manual_movements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  fecha TEXT NOT NULL,
  descripcion TEXT NOT NULL,
  monto REAL NOT NULL,
  tipo TEXT NOT NULL CHECK(tipo IN ('INGRESO','GASTO')),
  categoria TEXT,
  notas TEXT,
  period_month TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_manual_movements_issuer ON manual_movements(issuer_id);
CREATE INDEX IF NOT EXISTS idx_manual_movements_period ON manual_movements(issuer_id, period_month);
