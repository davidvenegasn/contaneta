-- Add CIEC (Contraseña SAT portal) to sat_credentials.
-- CIEC is the user's password to log into mi.sat.gob.mx for the official
-- consultation portal. Stored alongside the FIEL since they're both
-- credentials for the same tenant's SAT identity.
-- Encrypted at rest via crypto_at_rest.encrypt_text() — never stored plaintext.
ALTER TABLE sat_credentials ADD COLUMN ciec_password_encrypted TEXT;
