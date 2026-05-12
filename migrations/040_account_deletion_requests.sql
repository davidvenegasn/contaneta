-- LFPDPPP compliance: track account deletion (cancelación) requests
CREATE TABLE IF NOT EXISTS account_deletion_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    reason      TEXT,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'completed', 'rejected')),
    requested_at TEXT NOT NULL DEFAULT (datetime('now')),
    reviewed_at  TEXT,
    completed_at TEXT,
    reviewer_notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_deletion_requests_user
    ON account_deletion_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_deletion_requests_status
    ON account_deletion_requests(status);
