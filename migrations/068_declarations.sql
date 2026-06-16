-- 068: Declaration upload & tracking
-- Supports uploaded PDF declarations (acuses SAT) parsed by pdfplumber.

CREATE TABLE IF NOT EXISTS declarations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  uploaded_by_user_id INTEGER NOT NULL,
  tipo TEXT NOT NULL,                -- mensual_isr, mensual_iva, anual, pago_referenciado, etc.
  periodo_ym TEXT,                    -- 2026-05 for mensuales
  ejercicio INTEGER,                  -- 2026 for anuales
  fecha_presentacion TEXT,
  fecha_vencimiento TEXT,
  saldo_a_cargo REAL,
  saldo_a_favor REAL,
  total_a_pagar REAL,
  linea_captura TEXT,
  folio_acuse TEXT,
  numero_operacion TEXT,
  pdf_path TEXT NOT NULL,
  pdf_sha256 TEXT NOT NULL,
  parsed_at TEXT,
  parse_confidence REAL,
  parse_engine TEXT,                  -- pdfplumber-regex, manual
  raw_extracted_json TEXT,
  status TEXT NOT NULL DEFAULT 'pending_review',  -- pending_review, validated, pagada, vencida, rejected
  user_notification_sent_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE,
  FOREIGN KEY (uploaded_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_declarations_issuer_periodo
  ON declarations(issuer_id, periodo_ym DESC);
CREATE INDEX IF NOT EXISTS idx_declarations_status
  ON declarations(status);
CREATE INDEX IF NOT EXISTS idx_declarations_sha256
  ON declarations(pdf_sha256);

-- Track payment of each declaration
CREATE TABLE IF NOT EXISTS declaration_payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  declaration_id INTEGER NOT NULL,
  fecha_pago TEXT,
  monto REAL,
  comprobante_pago_path TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (declaration_id) REFERENCES declarations(id) ON DELETE CASCADE
);
