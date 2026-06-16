"""Tests for billing lifecycle — trial checker, plan limits, webhook helpers."""
import pytest

from database import db, db_rows
from services.subscription_lifecycle import (
    can_create_invoice,
    get_plan_limits,
    get_subscription_status,
    get_usage_metrics,
)

ISSUER_ID = 99940
USER_ID = 99940


@pytest.fixture(scope="module", autouse=True)
def seed():
    conn = db()
    conn.execute(
        "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
        "VALUES (?, 'BIL010101AAA', 'Billing Test SA', 1, datetime('now'), datetime('now'))",
        (ISSUER_ID,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
        "VALUES (?, 'billing@test.local', 'x', datetime('now'))",
        (USER_ID,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role, created_at) "
        "VALUES (?, ?, 'owner', datetime('now'))",
        (USER_ID, ISSUER_ID),
    )
    conn.commit()
    conn.close()
    yield


def test_should_return_plan_limits():
    """Plan limits should have expected keys."""
    limits = get_plan_limits("free")
    assert "invoices_per_month" in limits
    assert limits["invoices_per_month"] == 5

    limits_pro = get_plan_limits("pro")
    assert limits_pro["invoices_per_month"] == 500


def test_should_return_subscription_status():
    """Subscription status should return dict with plan info."""
    status = get_subscription_status(ISSUER_ID)
    assert "plan" in status
    assert "status" in status
    assert "plan_label" in status


def test_should_return_usage_metrics():
    """Usage metrics should have invoice count and percentages."""
    usage = get_usage_metrics(ISSUER_ID)
    assert "invoices_count" in usage
    assert "invoices_pct" in usage
    assert "storage_used_mb" in usage


def test_should_allow_invoice_creation_under_limit():
    """Under plan limit, can_create_invoice should return True."""
    assert can_create_invoice(ISSUER_ID) is True


def test_should_handle_unknown_plan():
    """Unknown plan should default to free limits."""
    limits = get_plan_limits("nonexistent_plan")
    assert limits["invoices_per_month"] == 5


def test_trial_checker_runs_without_error():
    """Trial checker should run without exceptions (even with no trials)."""
    from services.trial_checker import check_and_notify_trial_expiring
    count = check_and_notify_trial_expiring()
    assert isinstance(count, int)
    assert count >= 0
