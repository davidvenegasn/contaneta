-- Backfill trial_expires_at for recent issuers that were created without it.
-- Only issuers created in the last 7 days get the 14-day trial; older ones are unaffected.
UPDATE issuers
SET trial_expires_at = datetime('now', '+14 days')
WHERE trial_expires_at IS NULL
  AND created_at >= datetime('now', '-7 days');
