"""Tests for subscription lifecycle: service functions and portal route."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Fix DB path before importing app/config
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_subscription_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-subscription"

from fastapi.testclient import TestClient  # noqa: E402

from config import DB_PATH  # noqa: E402
from database import db  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402
from tests.helpers import make_session_cookie  # noqa: E402

from app import app  # noqa: E402

# Test constants (high IDs to avoid collisions)
ISSUER_ID = 9901
USER_ID = 9901


def _seed_data():
    """Create test issuer, user, and membership."""
    apply_migrations(DB_PATH)
    conn = db()
    try:
        # Clean up previous test data
        conn.execute("DELETE FROM memberships WHERE user_id = ? OR issuer_id = ?", (USER_ID, ISSUER_ID))
        conn.execute("DELETE FROM subscriptions WHERE user_id = ?", (USER_ID,))
        conn.execute("DELETE FROM plan_usage WHERE issuer_id = ?", (ISSUER_ID,))

        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'TEST9901RFC', 'Test Sub Corp', 1, datetime('now'), datetime('now'))",
            (ISSUER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
            "VALUES (?, 'sub_test@test.local', '$2b$12$x', datetime('now'))",
            (USER_ID,),
        )
        conn.execute(
            "INSERT INTO memberships (user_id, issuer_id, role, created_at) "
            "VALUES (?, ?, 'owner', datetime('now'))",
            (USER_ID, ISSUER_ID),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="module", autouse=True)
def seed():
    """Run seed once per test module."""
    _seed_data()
    yield
    # Cleanup
    conn = db()
    try:
        conn.execute("DELETE FROM memberships WHERE user_id = ? OR issuer_id = ?", (USER_ID, ISSUER_ID))
        conn.execute("DELETE FROM subscriptions WHERE user_id = ?", (USER_ID,))
        conn.execute("DELETE FROM plan_usage WHERE issuer_id = ?", (ISSUER_ID,))
        conn.commit()
    finally:
        conn.close()


# ---------- Service: get_plan_limits ----------

def test_should_return_free_plan_limits():
    from services.subscription_lifecycle import get_plan_limits
    limits = get_plan_limits("free")
    assert limits["name"] == "Gratis"
    assert limits["invoices_per_month"] == 5
    assert limits["storage_mb"] == 100
    assert "price_monthly" not in limits


def test_should_return_pro_plan_limits():
    from services.subscription_lifecycle import get_plan_limits
    limits = get_plan_limits("pro")
    assert limits["name"] == "Profesional"
    assert limits["invoices_per_month"] == 500
    assert limits["storage_mb"] == 5000
    assert limits["price_monthly"] == 299


def test_should_return_enterprise_plan_limits():
    from services.subscription_lifecycle import get_plan_limits
    limits = get_plan_limits("enterprise")
    assert limits["name"] == "Empresarial"
    assert limits["invoices_per_month"] == -1  # unlimited
    assert limits["storage_mb"] == 50000
    assert limits["price_monthly"] == 999


def test_should_default_to_free_for_unknown_plan():
    from services.subscription_lifecycle import get_plan_limits
    limits = get_plan_limits("nonexistent")
    assert limits["name"] == "Gratis"
    assert limits["invoices_per_month"] == 5


def test_should_default_to_free_for_empty_plan():
    from services.subscription_lifecycle import get_plan_limits
    limits = get_plan_limits("")
    assert limits["name"] == "Gratis"


# ---------- Service: get_subscription_status ----------

def test_should_return_free_status_when_no_subscription():
    from services.subscription_lifecycle import get_subscription_status
    status = get_subscription_status(ISSUER_ID)
    assert status["plan"] in ("free", "trial", "basic", "pro")
    assert "plan_label" in status
    assert "status" in status
    assert status["stripe_subscription_id"] is None


def test_should_return_active_status_when_subscription_exists():
    from services.subscription_lifecycle import get_subscription_status
    # Create a subscription for the test user
    conn = db()
    try:
        conn.execute("DELETE FROM subscriptions WHERE user_id = ?", (USER_ID,))
        conn.execute(
            "INSERT INTO subscriptions (user_id, plan, status, stripe_subscription_id, created_at, updated_at) "
            "VALUES (?, 'pro', 'active', 'sub_test_123', datetime('now'), datetime('now'))",
            (USER_ID,),
        )
        conn.commit()
    finally:
        conn.close()

    status = get_subscription_status(ISSUER_ID)
    assert status["status"] == "active"
    assert status["stripe_subscription_id"] == "sub_test_123"

    # Cleanup
    conn = db()
    try:
        conn.execute("DELETE FROM subscriptions WHERE user_id = ?", (USER_ID,))
        conn.commit()
    finally:
        conn.close()


# ---------- Service: get_usage_metrics ----------

def test_should_return_usage_metrics_with_zero_defaults():
    from services.subscription_lifecycle import get_usage_metrics
    metrics = get_usage_metrics(ISSUER_ID)
    assert "invoices_count" in metrics
    assert "storage_used_mb" in metrics
    assert "invoices_limit" in metrics
    assert "invoices_pct" in metrics
    assert "storage_pct" in metrics
    assert isinstance(metrics["invoices_count"], int)
    assert isinstance(metrics["storage_used_mb"], float)


def test_should_calculate_usage_percentage():
    from services.subscription_lifecycle import get_usage_metrics
    # Insert usage data
    from datetime import datetime
    ym = datetime.now().strftime("%Y-%m")
    conn = db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO plan_usage (issuer_id, ym, invoices_count, sat_syncs_count, bank_imports_count) "
            "VALUES (?, ?, 3, 1, 0)",
            (ISSUER_ID, ym),
        )
        conn.commit()
    finally:
        conn.close()

    metrics = get_usage_metrics(ISSUER_ID)
    assert metrics["invoices_count"] == 3
    assert metrics["invoices_pct"] == 60  # 3/5 * 100

    # Cleanup
    conn = db()
    try:
        conn.execute("DELETE FROM plan_usage WHERE issuer_id = ?", (ISSUER_ID,))
        conn.commit()
    finally:
        conn.close()


# ---------- Service: can_create_invoice ----------

def test_should_allow_invoice_when_under_limit():
    from services.subscription_lifecycle import can_create_invoice
    # Fresh state, 0 invoices used
    conn = db()
    try:
        conn.execute("DELETE FROM plan_usage WHERE issuer_id = ?", (ISSUER_ID,))
        conn.commit()
    finally:
        conn.close()
    assert can_create_invoice(ISSUER_ID) is True


def test_should_deny_invoice_when_at_limit():
    from services.subscription_lifecycle import can_create_invoice
    from datetime import datetime
    ym = datetime.now().strftime("%Y-%m")
    conn = db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO plan_usage (issuer_id, ym, invoices_count) VALUES (?, ?, 5)",
            (ISSUER_ID, ym),
        )
        conn.commit()
    finally:
        conn.close()

    # Free plan limit is 5, so at 5 it should deny
    assert can_create_invoice(ISSUER_ID) is False

    # Cleanup
    conn = db()
    try:
        conn.execute("DELETE FROM plan_usage WHERE issuer_id = ?", (ISSUER_ID,))
        conn.commit()
    finally:
        conn.close()


# ---------- Service: get_payment_history ----------

def test_should_return_empty_payment_history():
    from services.subscription_lifecycle import get_payment_history
    payments = get_payment_history(ISSUER_ID)
    assert isinstance(payments, list)


def test_should_return_payment_history_with_subscription():
    from services.subscription_lifecycle import get_payment_history
    conn = db()
    try:
        conn.execute("DELETE FROM subscriptions WHERE user_id = ?", (USER_ID,))
        conn.execute(
            "INSERT INTO subscriptions (user_id, plan, status, stripe_subscription_id, created_at, updated_at) "
            "VALUES (?, 'pro', 'active', 'sub_hist_123', datetime('now'), datetime('now'))",
            (USER_ID,),
        )
        conn.commit()
    finally:
        conn.close()

    payments = get_payment_history(ISSUER_ID)
    assert len(payments) >= 1
    assert payments[0]["plan"] == "pro"
    assert payments[0]["plan_label"] == "Profesional"
    assert payments[0]["status"] == "active"
    assert payments[0]["amount"] == 299

    # Cleanup
    conn = db()
    try:
        conn.execute("DELETE FROM subscriptions WHERE user_id = ?", (USER_ID,))
        conn.commit()
    finally:
        conn.close()


# ---------- Portal route: GET /portal/subscription ----------

def test_should_render_subscription_page_with_auth():
    client = TestClient(app)
    cookies = make_session_cookie(ISSUER_ID, user_id=USER_ID)
    r = client.get("/portal/subscription", cookies=cookies)
    assert r.status_code == 200
    assert "Mi suscripcion" in r.text
    assert "Uso del mes" in r.text
    assert "Planes disponibles" in r.text


def test_should_redirect_without_auth():
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/portal/subscription", follow_redirects=False)
    # Without session cookie, should get 401 (which triggers redirect to login)
    assert r.status_code in (401, 302, 307)


def test_should_show_payment_history_section():
    client = TestClient(app)
    cookies = make_session_cookie(ISSUER_ID, user_id=USER_ID)
    r = client.get("/portal/subscription", cookies=cookies)
    assert r.status_code == 200
    assert "Historial de pagos" in r.text


def test_should_show_plan_cards_in_page():
    client = TestClient(app)
    cookies = make_session_cookie(ISSUER_ID, user_id=USER_ID)
    r = client.get("/portal/subscription", cookies=cookies)
    assert r.status_code == 200
    assert "Profesional" in r.text
    assert "Empresarial" in r.text
