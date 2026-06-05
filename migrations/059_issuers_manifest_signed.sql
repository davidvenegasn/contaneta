-- Track Facturapi lifecycle state per issuer (tenant):
--   facturapi_provisioned_at: when POST /v2/organizations succeeded
--   manifest_signed_at: when the manifest.signed webhook arrived
-- Both are nullable; existing rows stay NULL until backfill or until each tenant runs the flow.
ALTER TABLE issuers ADD COLUMN facturapi_provisioned_at TEXT;
ALTER TABLE issuers ADD COLUMN manifest_signed_at TEXT;
