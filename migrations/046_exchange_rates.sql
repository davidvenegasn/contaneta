-- Daily DOF exchange rates cache (Banxico API)
-- Separate from the existing monthly exchange_rates table (migration 039)
CREATE TABLE IF NOT EXISTS dof_rates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,           -- YYYY-MM-DD (fecha de publicación del DOF)
  currency TEXT NOT NULL,       -- USD, EUR, GBP, JPY, CAD, CHF, ...
  rate_to_mxn REAL NOT NULL,   -- ej. 17.4523
  source TEXT NOT NULL DEFAULT 'banxico_dof',
  series TEXT,                  -- ej. SF43718
  fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(date, currency)
);
CREATE INDEX IF NOT EXISTS idx_dof_rates_date_currency ON dof_rates(date, currency);
CREATE INDEX IF NOT EXISTS idx_dof_rates_currency_date_desc ON dof_rates(currency, date DESC);
