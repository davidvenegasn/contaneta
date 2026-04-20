-- Exchange rates by month and currency (used for foreign invoices)
CREATE TABLE IF NOT EXISTS exchange_rates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  moneda TEXT NOT NULL,
  period_month TEXT NOT NULL,  -- YYYY-MM
  rate REAL NOT NULL,          -- 1 unit of moneda = rate MXN
  source TEXT DEFAULT 'manual',
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(moneda, period_month)
);

-- Pre-populate with approximate USD/MXN rates (Banxico averages)
INSERT OR IGNORE INTO exchange_rates (moneda, period_month, rate, source) VALUES
  ('USD', '2024-01', 17.15, 'seed'), ('USD', '2024-02', 17.10, 'seed'),
  ('USD', '2024-03', 16.80, 'seed'), ('USD', '2024-04', 17.05, 'seed'),
  ('USD', '2024-05', 16.95, 'seed'), ('USD', '2024-06', 18.15, 'seed'),
  ('USD', '2024-07', 18.05, 'seed'), ('USD', '2024-08', 19.20, 'seed'),
  ('USD', '2024-09', 19.60, 'seed'), ('USD', '2024-10', 19.80, 'seed'),
  ('USD', '2024-11', 20.30, 'seed'), ('USD', '2024-12', 20.15, 'seed'),
  ('USD', '2025-01', 20.50, 'seed'), ('USD', '2025-02', 20.40, 'seed'),
  ('USD', '2025-03', 20.25, 'seed'), ('USD', '2025-04', 19.90, 'seed'),
  ('USD', '2025-05', 19.55, 'seed'), ('USD', '2025-06', 19.70, 'seed'),
  ('USD', '2025-07', 19.85, 'seed'), ('USD', '2025-08', 19.60, 'seed'),
  ('USD', '2025-09', 19.50, 'seed'), ('USD', '2025-10', 20.00, 'seed'),
  ('USD', '2025-11', 20.20, 'seed'), ('USD', '2025-12', 20.35, 'seed'),
  ('USD', '2026-01', 20.50, 'seed'), ('USD', '2026-02', 20.60, 'seed'),
  ('USD', '2026-03', 20.45, 'seed');

-- EUR/MXN
INSERT OR IGNORE INTO exchange_rates (moneda, period_month, rate, source) VALUES
  ('EUR', '2024-01', 18.80, 'seed'), ('EUR', '2024-02', 18.55, 'seed'),
  ('EUR', '2024-03', 18.30, 'seed'), ('EUR', '2024-04', 18.20, 'seed'),
  ('EUR', '2024-05', 18.40, 'seed'), ('EUR', '2024-06', 19.50, 'seed'),
  ('EUR', '2024-07', 19.65, 'seed'), ('EUR', '2024-08', 21.30, 'seed'),
  ('EUR', '2024-09', 21.85, 'seed'), ('EUR', '2024-10', 21.50, 'seed'),
  ('EUR', '2024-11', 21.35, 'seed'), ('EUR', '2024-12', 21.10, 'seed'),
  ('EUR', '2025-01', 21.40, 'seed'), ('EUR', '2025-02', 21.50, 'seed'),
  ('EUR', '2025-03', 22.00, 'seed'), ('EUR', '2025-04', 22.30, 'seed'),
  ('EUR', '2025-05', 21.90, 'seed'), ('EUR', '2025-06', 22.00, 'seed'),
  ('EUR', '2025-07', 21.80, 'seed'), ('EUR', '2025-08', 21.60, 'seed'),
  ('EUR', '2025-09', 21.50, 'seed'), ('EUR', '2025-10', 21.80, 'seed'),
  ('EUR', '2025-11', 21.50, 'seed'), ('EUR', '2025-12', 21.70, 'seed'),
  ('EUR', '2026-01', 22.00, 'seed'), ('EUR', '2026-02', 22.10, 'seed'),
  ('EUR', '2026-03', 22.00, 'seed');

-- GBP/MXN
INSERT OR IGNORE INTO exchange_rates (moneda, period_month, rate, source) VALUES
  ('GBP', '2024-01', 21.60, 'seed'), ('GBP', '2024-06', 23.00, 'seed'),
  ('GBP', '2024-12', 25.50, 'seed'),
  ('GBP', '2025-01', 25.80, 'seed'), ('GBP', '2025-06', 24.90, 'seed'),
  ('GBP', '2025-12', 25.60, 'seed'),
  ('GBP', '2026-01', 25.90, 'seed'), ('GBP', '2026-02', 26.00, 'seed'),
  ('GBP', '2026-03', 25.80, 'seed');

-- CAD/MXN
INSERT OR IGNORE INTO exchange_rates (moneda, period_month, rate, source) VALUES
  ('CAD', '2024-01', 12.75, 'seed'), ('CAD', '2024-06', 13.30, 'seed'),
  ('CAD', '2024-12', 14.10, 'seed'),
  ('CAD', '2025-01', 14.30, 'seed'), ('CAD', '2025-06', 14.00, 'seed'),
  ('CAD', '2025-12', 14.20, 'seed'),
  ('CAD', '2026-01', 14.40, 'seed'), ('CAD', '2026-02', 14.50, 'seed'),
  ('CAD', '2026-03', 14.35, 'seed');
