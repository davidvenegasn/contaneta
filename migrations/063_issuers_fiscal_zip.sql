-- Adds fiscal_zip (CP fiscal) for each issuer. Required by Facturapi's
-- update_legal_info call to mark the org as fully configured and unlock
-- live-mode emission. SAT validates this against its records — must match
-- exactly the CP registered for the RFC.

ALTER TABLE issuers ADD COLUMN fiscal_zip TEXT;
