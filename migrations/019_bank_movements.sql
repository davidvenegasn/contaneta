-- Tabla de movimientos bancarios importados (por estado de cuenta / PDF convertido)
-- statement_file_id enlaza con bank_pdf_exports.file_id
CREATE TABLE IF NOT EXISTS bank_movements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  statement_file_id TEXT NOT NULL,
  fecha TEXT,
  descripcion TEXT,
  deposito REAL,
  retiro REAL,
  saldo REAL,
  tipo TEXT,
  categoria TEXT,
  metodo_hint TEXT,
  contraparte_hint TEXT,
  rfc_encontrado TEXT,
  confidence_score INTEGER,
  source_page_first INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_bank_movements_issuer_statement ON bank_movements(issuer_id, statement_file_id);
CREATE INDEX IF NOT EXISTS idx_bank_movements_issuer_tipo ON bank_movements(issuer_id, tipo);
CREATE INDEX IF NOT EXISTS idx_bank_movements_issuer_categoria ON bank_movements(issuer_id, categoria);
CREATE INDEX IF NOT EXISTS idx_bank_movements_issuer_fecha ON bank_movements(issuer_id, fecha);
CREATE INDEX IF NOT EXISTS idx_bank_movements_issuer_confidence ON bank_movements(issuer_id, confidence_score);
