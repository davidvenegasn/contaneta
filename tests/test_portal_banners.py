"""Tests for portal banner services (Phase 2)."""

from datetime import datetime, timedelta

import pytest

from database import db

ISSUER_ID = 99902


@pytest.fixture(scope="module", autouse=True)
def seed():
    """Ensure test issuer exists with relevant columns."""
    conn = db()
    conn.execute(
        """INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, regimen_fiscal)
           VALUES (?, 'XBAN020202BBB', 'Banner Test SA', 1, '601')""",
        (ISSUER_ID,),
    )
    # Add usage columns if missing (may not have migration yet)
    for col, ctype, default in [
        ("plan_invoice_limit", "INTEGER", "0"),
        ("plan_invoices_used", "INTEGER", "0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE issuers ADD COLUMN {col} {ctype} DEFAULT {default}")
        except Exception:
            pass  # column already exists
    conn.commit()
    conn.close()
    yield


def _update_issuer(**kwargs):
    """Helper to update test issuer columns."""
    conn = db()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    conn.execute(f"UPDATE issuers SET {sets} WHERE id = ?", (*kwargs.values(), ISSUER_ID))
    conn.commit()
    conn.close()


# --- Trial banner ---

def test_trial_banner_appears_when_expiring_soon():
    """Trial banner should appear when trial expires within 7 days."""
    from services.banners.trial_banner import compute_trial_banner_state
    expires = (datetime.now() + timedelta(days=5)).isoformat()
    _update_issuer(trial_expires_at=expires)
    result = compute_trial_banner_state(ISSUER_ID)
    assert result is not None
    assert result["key"] == "trial_expiring"
    assert result["variant"] == "warn"


def test_trial_banner_danger_when_3_days():
    """Trial banner should be danger when <= 3 days left."""
    from services.banners.trial_banner import compute_trial_banner_state
    expires = (datetime.now() + timedelta(days=2)).isoformat()
    _update_issuer(trial_expires_at=expires)
    result = compute_trial_banner_state(ISSUER_ID)
    assert result is not None
    assert result["variant"] == "danger"


def test_trial_banner_expired():
    """Trial banner should show expired when trial is past."""
    from services.banners.trial_banner import compute_trial_banner_state
    expires = (datetime.now() - timedelta(days=1)).isoformat()
    _update_issuer(trial_expires_at=expires)
    result = compute_trial_banner_state(ISSUER_ID)
    assert result is not None
    assert result["key"] == "trial_expired"
    assert result["variant"] == "danger"


def test_trial_banner_none_when_far():
    """No trial banner when trial expires in >7 days."""
    from services.banners.trial_banner import compute_trial_banner_state
    expires = (datetime.now() + timedelta(days=20)).isoformat()
    _update_issuer(trial_expires_at=expires)
    result = compute_trial_banner_state(ISSUER_ID)
    assert result is None


def test_trial_banner_none_when_no_trial():
    """No trial banner when no trial_expires_at set."""
    from services.banners.trial_banner import compute_trial_banner_state
    _update_issuer(trial_expires_at=None)
    result = compute_trial_banner_state(ISSUER_ID)
    assert result is None


# --- Onboarding banner ---

def test_onboarding_banner_appears_when_incomplete():
    """Onboarding banner should appear when step < 5."""
    from services.banners.onboarding_banner import compute_onboarding_banner_state
    _update_issuer(onboarding_step=2, onboarding_dismissed=0)
    result = compute_onboarding_banner_state(ISSUER_ID)
    assert result is not None
    assert result["key"] == "onboarding_incomplete"
    assert result["variant"] == "info"


def test_onboarding_banner_none_when_complete():
    """No banner when onboarding is complete (step >= 5)."""
    from services.banners.onboarding_banner import compute_onboarding_banner_state
    _update_issuer(onboarding_step=5, onboarding_dismissed=0)
    result = compute_onboarding_banner_state(ISSUER_ID)
    assert result is None


def test_onboarding_banner_none_when_dismissed():
    """No banner when onboarding is dismissed."""
    from services.banners.onboarding_banner import compute_onboarding_banner_state
    _update_issuer(onboarding_step=1, onboarding_dismissed=1)
    result = compute_onboarding_banner_state(ISSUER_ID)
    assert result is None


# --- Usage banner ---

def test_usage_banner_appears_at_80_percent():
    """Usage banner should appear when usage >= 80%."""
    from services.banners.usage_banner import compute_usage_banner_state
    _update_issuer(plan_invoice_limit=100, plan_invoices_used=85)
    result = compute_usage_banner_state(ISSUER_ID)
    assert result is not None
    assert result["key"] == "usage_limit_warning"
    assert result["variant"] == "warn"


def test_usage_banner_danger_at_100_percent():
    """Usage banner should be danger at 100%."""
    from services.banners.usage_banner import compute_usage_banner_state
    _update_issuer(plan_invoice_limit=100, plan_invoices_used=100)
    result = compute_usage_banner_state(ISSUER_ID)
    assert result is not None
    assert result["key"] == "usage_limit_reached"
    assert result["variant"] == "danger"


def test_usage_banner_none_when_low():
    """No usage banner when under 80%."""
    from services.banners.usage_banner import compute_usage_banner_state
    _update_issuer(plan_invoice_limit=100, plan_invoices_used=50)
    result = compute_usage_banner_state(ISSUER_ID)
    assert result is None


# --- Integration ---

def test_get_portal_banners_returns_list():
    """get_portal_banners should return a list of active banners."""
    from services.banners import get_portal_banners
    _update_issuer(
        trial_expires_at=(datetime.now() + timedelta(days=2)).isoformat(),
        onboarding_step=1,
        onboarding_dismissed=0,
    )
    banners = get_portal_banners(ISSUER_ID)
    assert isinstance(banners, list)
    assert len(banners) >= 2  # trial + onboarding at minimum
    keys = [b["key"] for b in banners]
    assert "onboarding_incomplete" in keys
