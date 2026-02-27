-- bank_statements: un registro por PDF subido (dedupe por sha256)
CREATE TABLE IF NOT EXISTS bank_statements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  bank_name TEXT,
  account_last4 TEXT,
  period_start TEXT,
  period_end TEXT,
  source_pdf_path TEXT NOT NULL,
  source_pdf_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bank_statements_issuer ON bank_statements(issuer_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bank_statements_issuer_sha ON bank_statements(issuer_id, source_pdf_sha256);

-- bank_movements: movimientos extraídos por statement (dedupe por movement_hash)
CREATE TABLE IF NOT EXISTS bank_movements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  statement_id INTEGER NOT NULL,
  movement_hash TEXT NOT NULL,
  fecha TEXT NOT NULL,
  descripcion_raw TEXT NOT NULL,
  descripcion_norm TEXT NOT NULL,
  deposito REAL DEFAULT 0,
  retiro REAL DEFAULT 0,
  saldo REAL,
  tipo TEXT NOT NULL,
  categoria TEXT,
  metodo_hint TEXT,
  contraparte_hint TEXT,
  referencia TEXT,
  cve_rastreo TEXT,
  rfc_detectado TEXT,
  confidence_score INTEGER NOT NULL DEFAULT 0,
  source_page_first INTEGER,
  source_page_last INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(issuer_id, movement_hash),
  FOREIGN KEY (statement_id) REFERENCES bank_statements(id)
);
CREATE INDEX IF NOT EXISTS idx_bank_movements_statement ON bank_movements(statement_id);
CREATE INDEX IF NOT EXISTS idx_bank_movements_issuer ON bank_movements(issuer_id);
