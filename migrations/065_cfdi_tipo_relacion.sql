-- Migration 065: add CFDI TipoRelacion + related UUIDs to sat_cfdi
-- Allows distinguishing nota de crédito vs aplicación de anticipo vs sustitución
-- for proper monthly net calculation per SAT prellenado semantics.

ALTER TABLE sat_cfdi ADD COLUMN IF NOT EXISTS tipo_relacion TEXT;
ALTER TABLE sat_cfdi ADD COLUMN IF NOT EXISTS related_uuids TEXT; -- JSON array of UUID strings

CREATE INDEX IF NOT EXISTS idx_sat_cfdi_tipo_relacion
  ON sat_cfdi(issuer_id, tipo_comprobante, tipo_relacion);
