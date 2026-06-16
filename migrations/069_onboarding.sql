-- 069: Onboarding wizard step tracking
ALTER TABLE issuers ADD COLUMN onboarding_step INTEGER NOT NULL DEFAULT 0;
ALTER TABLE issuers ADD COLUMN onboarding_dismissed INTEGER NOT NULL DEFAULT 0;
