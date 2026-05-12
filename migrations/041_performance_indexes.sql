-- Performance indexes for frequently-queried paths
-- All use IF NOT EXISTS for idempotency

-- speeds up: worker job dedupe check (issuer_id + name + payload_hash + status)
CREATE INDEX IF NOT EXISTS idx_jobs_issuer_name_hash_status
    ON jobs (issuer_id, name, payload_hash, status);

-- speeds up: dashboard status counts, portal deduction checks (issuer_id + direction + status)
CREATE INDEX IF NOT EXISTS idx_sat_cfdi_issuer_direction_status
    ON sat_cfdi (issuer_id, direction, status);

-- speeds up: invoice creation profile lookup, catalog sync (issuer_id + rfc)
CREATE INDEX IF NOT EXISTS idx_customer_profiles_issuer_rfc
    ON customer_profiles (issuer_id, rfc);

-- speeds up: reconciliation page aggregations (issuer_id + period_month + categoria)
CREATE INDEX IF NOT EXISTS idx_bank_movements_issuer_period_cat
    ON bank_movements (issuer_id, period_month, categoria);

-- speeds up: pending invoice listings sorted by date (issuer_id + payment_method + issue_date DESC)
CREATE INDEX IF NOT EXISTS idx_invoices_issuer_pm_date
    ON invoices (issuer_id, payment_method, issue_date DESC);
