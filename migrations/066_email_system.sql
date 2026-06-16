-- Migration 066: email_log table + per-issuer/customer toggles
-- Allows tracking all transactional emails (invoice, declaration, alerts)
-- and lets issuers/customers opt out of auto-sending.

CREATE TABLE IF NOT EXISTS email_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER,
  user_id INTEGER,
  email_type TEXT NOT NULL,              -- 'invoice_sent', 'declaration_summary', 'welcome', etc.
  related_object_type TEXT,              -- 'invoice', 'declaration', 'user', NULL
  related_object_id INTEGER,
  to_email TEXT NOT NULL,
  to_name TEXT,
  from_email TEXT,
  from_name TEXT,
  reply_to TEXT,
  subject TEXT,
  template TEXT,                          -- template name used, e.g. 'invoice_sent'
  provider TEXT,                          -- 'resend', 'noop', 'postmark', etc.
  provider_message_id TEXT,               -- ID returned by provider for tracking
  status TEXT NOT NULL DEFAULT 'queued',  -- queued, sent, delivered, bounced, failed, opened, clicked
  error_message TEXT,
  payload_json TEXT,                      -- snapshot of context vars used to render
  sent_at TEXT,
  delivered_at TEXT,
  opened_at TEXT,
  clicked_at TEXT,
  bounced_at TEXT,
  failed_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_email_log_issuer_created
  ON email_log(issuer_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_log_status
  ON email_log(status);
CREATE INDEX IF NOT EXISTS idx_email_log_provider_msg
  ON email_log(provider_message_id);
CREATE INDEX IF NOT EXISTS idx_email_log_related
  ON email_log(related_object_type, related_object_id);

-- Per-issuer toggle: master kill-switch for transactional emails
ALTER TABLE issuers ADD COLUMN email_notifications_enabled INTEGER NOT NULL DEFAULT 1;

-- Per-customer toggle: don't auto-send invoices to this client
ALTER TABLE customer_profiles ADD COLUMN auto_send_invoices INTEGER NOT NULL DEFAULT 1;
