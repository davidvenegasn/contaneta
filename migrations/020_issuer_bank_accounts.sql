-- Cuentas bancarias del usuario/issuer para detectar transferencias entre cuentas propias (preview).
-- NO guarda movimientos; solo configuración para clasificación.
CREATE TABLE IF NOT EXISTS issuer_bank_accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  alias TEXT NOT NULL,
  bank_name TEXT NOT NULL,
  clabe TEXT,
  account_last4 TEXT,
  holder_name TEXT,
  rfc_titular TEXT,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_issuer_bank_accounts_issuer ON issuer_bank_accounts(issuer_id);
CREATE INDEX IF NOT EXISTS idx_issuer_bank_accounts_active ON issuer_bank_accounts(issuer_id, is_active);
