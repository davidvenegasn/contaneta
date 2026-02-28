-- 026_month_close_status.sql
-- Estado de cierre mensual (PF): checklist + uploads ligados a YYYY-MM.

CREATE TABLE IF NOT EXISTS month_close_status (
  issuer_id INTEGER NOT NULL,
  ym TEXT NOT NULL,                      -- YYYY-MM
  status_json TEXT,                      -- overrides / flags / notes
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (issuer_id, ym),
  FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_month_close_status_issuer ON month_close_status(issuer_id, ym);

