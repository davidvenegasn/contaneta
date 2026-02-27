CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',           -- queued/running/success/failed
  progress INTEGER NOT NULL DEFAULT 0,             -- 0-100
  message TEXT,
  payload_json TEXT,
  result_json TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_jobs_issuer_created
  ON jobs(issuer_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_jobs_status
  ON jobs(status);

