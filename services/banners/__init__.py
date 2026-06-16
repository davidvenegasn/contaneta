"""Persistent portal banners: trial, usage, onboarding."""

from services.banners.onboarding_banner import compute_onboarding_banner_state
from services.banners.trial_banner import compute_trial_banner_state
from services.banners.usage_banner import compute_usage_banner_state

__all__ = [
    "compute_trial_banner_state",
    "compute_usage_banner_state",
    "compute_onboarding_banner_state",
    "get_portal_banners",
]


def get_portal_banners(issuer_id: int) -> list[dict]:
    """Return list of active banners for a given issuer."""
    banners = []
    for fn in (
        compute_onboarding_banner_state,
        compute_trial_banner_state,
        compute_usage_banner_state,
    ):
        try:
            b = fn(issuer_id)
            if b:
                banners.append(b)
        except Exception:
            pass  # banners are non-critical
    return banners
