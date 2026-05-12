"""E2E test fixtures — Playwright browser with signed session cookie."""
import os
import sys

import pytest

# Ensure project root is in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
# Test user — must exist in DB. Override with env vars.
TEST_USER_ID = int(os.environ.get("E2E_USER_ID", "4"))
TEST_ISSUER_ID = int(os.environ.get("E2E_ISSUER_ID", "4"))


@pytest.fixture(scope="session")
def signed_cookie():
    """Generate a signed session cookie for E2E tests."""
    from config import SESSION_COOKIE_NAME
    from services.auth.session import sign_session

    value = sign_session(user_id=TEST_USER_ID, issuer_id=TEST_ISSUER_ID)
    return {"name": SESSION_COOKIE_NAME, "value": value, "domain": "localhost", "path": "/"}


@pytest.fixture(scope="session")
def browser_context_args(signed_cookie):
    """Inject session cookie into browser context."""
    return {
        "base_url": BASE_URL,
        "storage_state": {
            "cookies": [signed_cookie],
            "origins": [],
        },
    }
