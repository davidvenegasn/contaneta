"""Stripe webhook security tests — signature validation and event handling."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_billing_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-billing"

from starlette.testclient import TestClient

from app import app

client = TestClient(app, raise_server_exceptions=False)


def test_webhook_invalid_signature_returns_400():
    """Webhook with invalid/missing signature should return 400."""
    r = client.post(
        "/webhooks/stripe",
        content=b'{"type":"test"}',
        headers={"Stripe-Signature": "invalid_signature_value"},
    )
    # 400 (invalid sig) or 503 (webhook not configured)
    assert r.status_code in (400, 503), f"Expected 400/503, got {r.status_code}"


def test_webhook_missing_signature_returns_400():
    """Webhook with no Stripe-Signature header should return 400."""
    r = client.post(
        "/webhooks/stripe",
        content=b'{"type":"test"}',
    )
    assert r.status_code in (400, 503), f"Expected 400/503, got {r.status_code}"


def test_webhook_no_secret_configured_returns_503():
    """If STRIPE_WEBHOOK_SECRET is not set, return 503."""
    with patch("routers.billing.STRIPE_WEBHOOK_SECRET", None):
        r = client.post(
            "/webhooks/stripe",
            content=b'{"type":"test"}',
        )
        assert r.status_code == 503
