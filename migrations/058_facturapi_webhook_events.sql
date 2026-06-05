-- Inbound webhook events from Facturapi. One row per unique event_id (idempotency).
CREATE TABLE IF NOT EXISTS facturapi_webhook_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  received_at TEXT NOT NULL DEFAULT (datetime('now')),
  processed_at TEXT,
  process_error TEXT
);
CREATE INDEX IF NOT EXISTS idx_facturapi_webhook_events_type ON facturapi_webhook_events(event_type);
CREATE INDEX IF NOT EXISTS idx_facturapi_webhook_events_received_at ON facturapi_webhook_events(received_at);
