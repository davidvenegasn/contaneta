-- 005_users_and_memberships.sql
-- Usuarios (correo o teléfono, contraseña o OAuth) y membresías por issuer (roles).
-- Permite signup/login con email/tel + contraseña o con Google/Facebook.

PRAGMA foreign_keys = ON;

-- Usuarios: al menos uno de (email, phone) o (oauth_provider, oauth_id) debe identificar.
-- password_hash NULL = usuario solo OAuth.
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT,
  phone TEXT,
  password_hash TEXT,
  oauth_provider TEXT,
  oauth_id TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(email),
  UNIQUE(phone)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone ON users(phone) WHERE phone IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_oauth ON users(oauth_provider, oauth_id) WHERE oauth_provider IS NOT NULL AND oauth_id IS NOT NULL;

-- Membresías: usuario tiene acceso a un issuer con un rol.
-- role: 'viewer' | 'accountant' | 'owner'
CREATE TABLE IF NOT EXISTS memberships (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  issuer_id INTEGER NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('viewer', 'accountant', 'owner')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(user_id, issuer_id),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_memberships_user_id ON memberships(user_id);
CREATE INDEX IF NOT EXISTS idx_memberships_issuer_id ON memberships(issuer_id);
