-- Migration 067: cancellation status tracking for CFDI

ALTER TABLE sat_cfdi ADD COLUMN cancellation_status TEXT;
ALTER TABLE sat_cfdi ADD COLUMN cancellation_motivo TEXT;
ALTER TABLE sat_cfdi ADD COLUMN cancellation_substitute_uuid TEXT;
ALTER TABLE sat_cfdi ADD COLUMN cancellation_requested_at TEXT;
ALTER TABLE sat_cfdi ADD COLUMN cancellation_finalized_at TEXT;
ALTER TABLE sat_cfdi ADD COLUMN cancellation_requested_by_user_id INTEGER;

CREATE INDEX IF NOT EXISTS idx_sat_cfdi_cancel_status
  ON sat_cfdi(cancellation_status)
  WHERE cancellation_status IS NOT NULL;

-- Audit log specifically for cancellations
CREATE TABLE IF NOT EXISTS cancellation_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  cfdi_uuid TEXT NOT NULL,
  motivo TEXT NOT NULL,
  substitute_uuid TEXT,
  event TEXT NOT NULL,
  provider_response_json TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cancellation_log_issuer
  ON cancellation_log(issuer_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cancellation_log_uuid
  ON cancellation_log(cfdi_uuid);
