-- Add scheduled_for column to account_deletion_requests for 30-day grace period
ALTER TABLE account_deletion_requests ADD COLUMN scheduled_for TEXT;
