-- 051_performance_indexes.sql
-- Add indexes on frequently queried columns to improve query performance.
-- All statements are idempotent (IF NOT EXISTS).

-- Invoices: filter by issuer + date, issuer + status
CREATE INDEX IF NOT EXISTS idx_invoices_issuer_date ON invoices(issuer_id, created_at);
CREATE INDEX IF NOT EXISTS idx_invoices_issuer_status ON invoices(issuer_id, status);

-- Customer profiles: filter by issuer
CREATE INDEX IF NOT EXISTS idx_customer_profiles_issuer ON customer_profiles(issuer_id);

-- Products: filter by issuer
CREATE INDEX IF NOT EXISTS idx_products_issuer ON products(issuer_id);

-- Bank movements: filter by issuer + date
CREATE INDEX IF NOT EXISTS idx_bank_movements_issuer_date ON bank_movements(issuer_id, fecha);

-- Quotations: filter by issuer + status
CREATE INDEX IF NOT EXISTS idx_quotations_issuer_status ON quotations(issuer_id, status);

-- Notifications: filter by issuer + read status
CREATE INDEX IF NOT EXISTS idx_notifications_issuer_read ON notifications(issuer_id, read_at);

-- Jobs: filter by status (already exists from 024 but idempotent)
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
