-- 017_sat_cfdi_issuer_uuid_index.sql
-- Índice para búsqueda de detalle por (issuer_id, uuid) en sat_cfdi.
-- Equivalente al script legacy db_migrate_009_sat_cfdi_list_indexes.py (solo idx_sat_cfdi_issuer_uuid).
-- Idempotente: IF NOT EXISTS.

CREATE INDEX IF NOT EXISTS idx_sat_cfdi_issuer_uuid ON sat_cfdi(issuer_id, uuid);
