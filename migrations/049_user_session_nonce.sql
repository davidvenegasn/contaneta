-- Session nonce: rotated on password change to cryptographically invalidate all sessions.
-- Included in HMAC key derivation so old sessions fail signature verification.
ALTER TABLE users ADD COLUMN session_nonce TEXT;
