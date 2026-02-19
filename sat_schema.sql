PRAGMA foreign_keys = ON;

-- Credenciales SAT por emisor (FIEL)
CREATE TABLE IF NOT EXISTS sat_credentials (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL UNIQUE,
  fiel_cer_path TEXT NOT NULL,
  fiel_key_path TEXT NOT NULL,
  fiel_key_password TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
);

-- Checkpoints para sincronización incremental
CREATE TABLE IF NOT EXISTS sat_sync_state (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  direction TEXT NOT NULL CHECK(direction IN ('issued','received')),
  last_sync_from TEXT,
  last_sync_to TEXT,
  last_run_at TEXT,
  UNIQUE(issuer_id, direction),
  FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
);

-- CFDI descargados del SAT
CREATE TABLE IF NOT EXISTS sat_cfdi (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  direction TEXT NOT NULL CHECK(direction IN ('issued','received')),
  uuid TEXT NOT NULL,
  status TEXT,
  fecha_emision TEXT,
  rfc_emisor TEXT,
  nombre_emisor TEXT,
  rfc_receptor TEXT,
  nombre_receptor TEXT,
  total REAL,
  moneda TEXT,
  tipo_comprobante TEXT,
  xml_path TEXT,
  metadata_json TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(issuer_id, direction, uuid),
  FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sat_cfdi_issuer_dir_fecha
ON sat_cfdi(issuer_id, direction, fecha_emision);