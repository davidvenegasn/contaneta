"""Daily check for expiring credentials (CSD, FIEL, trial).

This module is a stub — the actual cron/scheduler integration is a follow-up job.
"""


# TODO: cron job that iterates issuers and enqueues csd_expiring / fiel_expiring / trial_expiring emails
def check_and_notify_expiring_credentials():
    """Check all issuers for expiring CSD/FIEL/trial and enqueue notification emails."""
    pass
