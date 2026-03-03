-- Performance indices for common query patterns (idempotent)
CREATE INDEX IF NOT EXISTS idx_sat_cfdi_issuer_date ON sat_cfdi(issuer_id, fecha_emision);
CREATE INDEX IF NOT EXISTS idx_jobs_status_run ON jobs(status, run_after);
CREATE INDEX IF NOT EXISTS idx_sat_jobs_issuer ON sat_jobs(issuer_id, status);
