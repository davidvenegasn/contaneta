-- Team invites: pending invitations for new members
CREATE TABLE IF NOT EXISTS membership_invites (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  invited_by_user_id INTEGER NOT NULL,
  email TEXT NOT NULL,
  role TEXT NOT NULL,
  token TEXT NOT NULL UNIQUE,
  expires_at TEXT NOT NULL,
  accepted_at TEXT,
  accepted_by_user_id INTEGER,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_membership_invites_email ON membership_invites(email, status);
CREATE INDEX IF NOT EXISTS idx_membership_invites_token ON membership_invites(token);
