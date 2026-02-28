-- 031_plans.sql
-- Plan definitions and issuer plan tracking.

-- Add plan columns to issuers table
ALTER TABLE issuers ADD COLUMN plan TEXT NOT NULL DEFAULT 'free';
-- plan: free | trial | basic | pro

ALTER TABLE issuers ADD COLUMN plan_invoices_limit INTEGER NOT NULL DEFAULT 5;
ALTER TABLE issuers ADD COLUMN plan_sat_syncs_limit INTEGER NOT NULL DEFAULT 0;
ALTER TABLE issuers ADD COLUMN plan_bank_accounts_limit INTEGER NOT NULL DEFAULT 1;

-- Track usage counters per month
CREATE TABLE IF NOT EXISTS plan_usage (
  issuer_id INTEGER NOT NULL,
  ym TEXT NOT NULL,
  invoices_count INTEGER NOT NULL DEFAULT 0,
  sat_syncs_count INTEGER NOT NULL DEFAULT 0,
  bank_imports_count INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (issuer_id, ym),
  FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
);
