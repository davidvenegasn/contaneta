-- 007_audit_log_and_admin_role.sql
-- Tabla audit_log para registrar acciones sensibles (ej. impersonación).
-- Añade rol 'admin' a memberships (recrear tabla por CHECK en SQLite).

PRAGMA foreign_keys = ON;

-- Tabla audit_log mínima
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  action TEXT NOT NULL,
  user_id INTEGER,
  issuer_id INTEGER,
  target_issuer_id INTEGER,
  details TEXT,
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (issuer_id) REFERENCES issuers(id),
  FOREIGN KEY (target_issuer_id) REFERENCES issuers(id)
);
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_id);

-- Recrear memberships para añadir rol 'admin' al CHECK
CREATE TABLE IF NOT EXISTS memberships_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  issuer_id INTEGER NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('viewer', 'accountant', 'owner', 'admin')),
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
