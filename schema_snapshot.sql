CREATE TABLE sat_credentials (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL UNIQUE,
  fiel_cer_path TEXT NOT NULL,
  fiel_key_path TEXT NOT NULL,
  fiel_key_password TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
);
CREATE TABLE sqlite_sequence(name,seq);
CREATE TABLE sat_sync_state (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  direction TEXT NOT NULL CHECK(direction IN ('issued','received')),
  last_sync_from TEXT,
  last_sync_to TEXT,
  last_run_at TEXT,
  UNIQUE(issuer_id, direction),
  FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
);
CREATE TABLE sat_cfdi (
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
  updated_at TEXT NOT NULL DEFAULT (datetime('now')), serie TEXT, folio TEXT, forma_pago TEXT, metodo_pago TEXT, uso_cfdi TEXT, subtotal REAL, descuento REAL, impuestos REAL, lugar_expedicion TEXT, condiciones_pago TEXT, xml_status TEXT, xml_sha256 TEXT, xml_downloaded_at TEXT, parsed_at TEXT, parse_version INTEGER, concepto TEXT, retenciones REAL,
  UNIQUE(issuer_id, direction, uuid),
  FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
);
CREATE INDEX idx_sat_cfdi_issuer_dir_fecha
ON sat_cfdi(issuer_id, direction, fecha_emision);
CREATE TABLE issuers (
  id INTEGER PRIMARY KEY,
  rfc TEXT,
  razon_social TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
, active INTEGER NOT NULL DEFAULT 1, regimen_fiscal TEXT);
CREATE TABLE customer_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issuer_id INTEGER NOT NULL,
                rfc TEXT NOT NULL,
                legal_name TEXT NOT NULL,
                zip TEXT NOT NULL,
                tax_system TEXT NOT NULL,
                email TEXT,
                alias TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(issuer_id, rfc),
                FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
            );
CREATE INDEX idx_customer_profiles_issuer_id ON customer_profiles(issuer_id);
CREATE INDEX idx_customer_profiles_alias ON customer_profiles(alias);
CREATE TABLE supplier_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issuer_id INTEGER NOT NULL,
                rfc TEXT NOT NULL,
                legal_name TEXT NOT NULL,
                zip TEXT,
                tax_system TEXT,
                email TEXT,
                alias TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(issuer_id, rfc),
                FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
            );
CREATE INDEX idx_supplier_profiles_issuer_id ON supplier_profiles(issuer_id);
CREATE INDEX idx_supplier_profiles_alias ON supplier_profiles(alias);
CREATE TABLE payment_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_invoice_id INTEGER NOT NULL,     -- local invoices.id for CFDI type P
                related_invoice_id INTEGER NOT NULL,     -- local invoices.id being paid
                related_uuid TEXT NOT NULL,
                amount REAL NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (payment_invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
                FOREIGN KEY (related_invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
            );
CREATE INDEX idx_payment_relations_payment ON payment_relations(payment_invoice_id);
CREATE INDEX idx_payment_relations_related ON payment_relations(related_invoice_id);
CREATE TABLE issuer_tokens (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_id INTEGER NOT NULL,
  token TEXT NOT NULL UNIQUE,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
);
CREATE INDEX idx_issuer_tokens_issuer_id ON issuer_tokens(issuer_id);
CREATE TABLE sat_requests (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          issuer_id INTEGER NOT NULL,
          direction TEXT NOT NULL CHECK(direction IN ('issued','received')),
          request_id TEXT NOT NULL UNIQUE,
          window_from TEXT NOT NULL,
          window_to TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'queued'
            CHECK(status IN ('queued','verifying','finished','error')),
          tries INTEGER NOT NULL DEFAULT 0,
          last_error TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
        );
CREATE INDEX idx_sat_requests_status ON sat_requests(status);
CREATE INDEX idx_sat_requests_issuer ON sat_requests(issuer_id, direction, status);
CREATE INDEX idx_sat_cfdi_xml_status ON sat_cfdi(xml_status);
CREATE INDEX idx_sat_cfdi_serie_folio ON sat_cfdi(serie, folio);
CREATE INDEX idx_sat_cfdi_metodo_pago ON sat_cfdi(metodo_pago);
CREATE TABLE sat_jobs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          issuer_id INTEGER NOT NULL,
          job_type TEXT NOT NULL CHECK(job_type IN ('metadata','xml','parse')),
          direction TEXT CHECK(direction IN ('issued','received')),
          window_from TEXT,
          window_to TEXT,
          status TEXT NOT NULL DEFAULT 'queued'
            CHECK(status IN ('queued','running','ok','error')),
          attempts INTEGER NOT NULL DEFAULT 0,
          locked_at TEXT,
          started_at TEXT,
          finished_at TEXT,
          last_error TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
        );
CREATE INDEX idx_sat_jobs_status ON sat_jobs(status);
CREATE INDEX idx_sat_jobs_issuer ON sat_jobs(issuer_id, job_type, status);
CREATE TABLE issuer_products (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              issuer_id INTEGER NOT NULL,
              description TEXT NOT NULL,
              product_key TEXT NOT NULL,
              unit_key TEXT NOT NULL DEFAULT 'E48',
              unit_price REAL NOT NULL,
              iva_rate REAL NOT NULL DEFAULT 0.16,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
            );
CREATE INDEX idx_issuer_products_issuer ON issuer_products(issuer_id);
CREATE TABLE quotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issuer_id INTEGER NOT NULL,
                customer_rfc TEXT NOT NULL,
                customer_legal_name TEXT NOT NULL,
                customer_email TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                public_token TEXT UNIQUE NOT NULL,
                valid_until TEXT,
                notes TEXT,
                responded_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')), folio TEXT, iva_rate REAL, sent_at TEXT, accepted_at TEXT, rejected_at TEXT, decision_ip TEXT, decision_user_agent TEXT, rejection_reason TEXT, currency TEXT,
                FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
            );
CREATE INDEX idx_quotations_issuer_id ON quotations(issuer_id);
CREATE UNIQUE INDEX idx_quotations_public_token ON quotations(public_token);
CREATE TABLE quotation_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quotation_id INTEGER NOT NULL,
                description TEXT NOT NULL,
                quantity REAL NOT NULL DEFAULT 1,
                unit_price REAL NOT NULL DEFAULT 0,
                iva_rate REAL NOT NULL DEFAULT 0.16,
                product_id INTEGER,
                sort_order INTEGER NOT NULL DEFAULT 0, extra_desc TEXT,
                FOREIGN KEY (quotation_id) REFERENCES quotations(id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES issuer_products(id) ON DELETE SET NULL
            );
CREATE INDEX idx_quotation_items_quotation_id ON quotation_items(quotation_id);
