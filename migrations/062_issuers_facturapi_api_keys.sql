-- 062: Per-org Facturapi API keys for CFDI emission.
-- The User Secret Key (sk_user_*) only admin-manages orgs; emission
-- requires each org's own API key (sk_test_*/sk_live_*).
-- Keys are stored encrypted at rest via crypto_at_rest.

ALTER TABLE issuers ADD COLUMN facturapi_test_key_encrypted TEXT;
ALTER TABLE issuers ADD COLUMN facturapi_live_key_encrypted TEXT;
ALTER TABLE issuers ADD COLUMN facturapi_keys_fetched_at TEXT;
