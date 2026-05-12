-- Issuer fiscal profile: regime selection for tax estimation
CREATE TABLE IF NOT EXISTS issuer_fiscal_profile (
  issuer_id INTEGER PRIMARY KEY,
  regimen TEXT NOT NULL DEFAULT 'RESICO_PF',  -- 'RESICO_PF', 'PFAE_GENERAL', 'PM_GENERAL' (futuro)
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
