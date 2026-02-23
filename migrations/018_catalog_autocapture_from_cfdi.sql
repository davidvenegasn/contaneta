-- 018_catalog_autocapture_from_cfdi.sql
-- Auto-captura de clientes y productos sugeridos desde CFDI emitidos (issued).
-- Crea tablas: clients, product_observations, products + índices recomendados.
-- Idempotente: IF NOT EXISTS.

PRAGMA foreign_keys = ON;

-- 1) clients (clientes sugeridos / auto-capturados)
CREATE TABLE IF NOT EXISTS clients (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  rfc TEXT NOT NULL,
  name TEXT,
  cp TEXT NULL,
  regimen_fiscal TEXT NULL,
  uso_cfdi_default TEXT NULL,
  email TEXT NULL,
  phone TEXT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  last_seen_at TEXT NULL,
  UNIQUE(issuer_id, rfc),
  FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_clients_issuer_name ON clients(issuer_id, name);

-- 2) product_observations (conceptos vistos en CFDI emitidos)
CREATE TABLE IF NOT EXISTS product_observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  clave_prod_serv TEXT NULL,
  clave_unidad TEXT NULL,
  unidad TEXT NULL,
  raw_description TEXT NOT NULL,
  unit_price_hint REAL NULL,
  currency TEXT NULL,
  tax_profile_hint TEXT NULL,
  times_seen INTEGER NOT NULL DEFAULT 1,
  last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(issuer_id, clave_prod_serv, clave_unidad, raw_description),
  FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_product_observations_issuer_times_seen ON product_observations(issuer_id, times_seen DESC);

-- 3) products (catálogo confirmado)
CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  clave_prod_serv TEXT NULL,
  clave_unidad TEXT NULL,
  unidad TEXT NULL,
  default_unit_price REAL NULL,
  default_currency TEXT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(issuer_id, name, clave_prod_serv, clave_unidad),
  FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_products_issuer_active ON products(issuer_id, active);

