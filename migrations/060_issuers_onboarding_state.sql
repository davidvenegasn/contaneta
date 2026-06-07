-- Track full onboarding lifecycle per issuer:
--   csd_uploaded_at: when CSD was successfully sent to Facturapi
--   onboarding_completed_at: when FIEL + CSD + manifesto are all done
-- Together with manifest_signed_at (migration 059) and facturapi_provisioned_at,
-- these let the UI render a precise progress state.
ALTER TABLE issuers ADD COLUMN csd_uploaded_at TEXT;
ALTER TABLE issuers ADD COLUMN onboarding_completed_at TEXT;
