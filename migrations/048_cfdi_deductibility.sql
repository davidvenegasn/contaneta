CREATE TABLE IF NOT EXISTS cfdi_deductibility (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cfdi_uuid TEXT NOT NULL,
  issuer_id INTEGER NOT NULL,
  percentage REAL NOT NULL DEFAULT 100 CHECK(percentage >= 0 AND percentage <= 100),
  source TEXT NOT NULL DEFAULT 'default' CHECK(source IN ('auto','manual','default')),
  auto_reason TEXT,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(cfdi_uuid, issuer_id)
);
CREATE INDEX IF NOT EXISTS idx_cfdi_deduct_issuer ON cfdi_deductibility(issuer_id);
CREATE INDEX IF NOT EXISTS idx_cfdi_deduct_uuid ON cfdi_deductibility(cfdi_uuid);
