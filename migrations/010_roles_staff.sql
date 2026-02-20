-- 010_roles_staff.sql
-- Añade rol 'staff' al CHECK de memberships (owner, admin, staff, viewer + accountant).
-- SQLite no permite ALTER CONSTRAINT; se recrea la tabla como en 007.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS memberships_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  issuer_id INTEGER NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('viewer', 'accountant', 'owner', 'admin', 'staff')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(user_id, issuer_id),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
);
INSERT INTO memberships_new (id, user_id, issuer_id, role, created_at)
  SELECT id, user_id, issuer_id, role, created_at FROM memberships;
DROP TABLE memberships;
ALTER TABLE memberships_new RENAME TO memberships;
CREATE INDEX IF NOT EXISTS idx_memberships_user_id ON memberships(user_id);
CREATE INDEX IF NOT EXISTS idx_memberships_issuer_id ON memberships(issuer_id);
