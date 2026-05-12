"""Tests for the onboarding wizard flow (GET/POST /onboarding)."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Setup test DB before importing app/config
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_onboarding_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-onboarding"

from fastapi.testclient import TestClient  # noqa: E402

from config import DB_PATH  # noqa: E402
from database import db, db_rows  # noqa: E402
from services.auth import csrf as csrf_service  # noqa: E402
from tests.helpers import make_session_cookie  # noqa: E402
from app import app  # noqa: E402


# High IDs to avoid collisions with other test suites
ISSUER_ID = 7701
USER_ID = 7701

# Create the client once — triggers lifespan (which applies migrations)
_client = TestClient(app)


def _seed():
    """Create minimal user + issuer with RFC=PENDIENTE (new user state)."""
    conn = db()
    try:
        conn.execute(
            "DELETE FROM sat_credentials WHERE issuer_id = ?", (ISSUER_ID,)
        )
        conn.execute(
            "DELETE FROM memberships WHERE user_id = ? OR issuer_id = ?",
            (USER_ID, ISSUER_ID),
        )
        conn.execute("DELETE FROM users WHERE id = ?", (USER_ID,))
        conn.execute("DELETE FROM issuers WHERE id = ?", (ISSUER_ID,))
        conn.execute(
            "INSERT INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'PENDIENTE', 'Test Onboarding', 1, datetime('now'), datetime('now'))",
            (ISSUER_ID,),
        )
        conn.execute(
            "INSERT INTO users (id, email, password_hash, created_at) "
            "VALUES (?, 'onboarding@test.local', '$2b$12$x', datetime('now'))",
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


def _seed_with_rfc():
    """Create user + issuer with valid RFC (post step 1)."""
    _seed()
    conn = db()
    try:
        conn.execute(
            "UPDATE issuers SET rfc = 'XAXX010101000', razon_social = 'Test Corp SA' WHERE id = ?",
            (ISSUER_ID,),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_with_fiel():
    """Create user + issuer with RFC + FIEL credentials (post step 2)."""
    _seed_with_rfc()
    conn = db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO sat_credentials "
            "(issuer_id, fiel_cer_path, fiel_key_path, fiel_key_password, "
            "created_at, updated_at) "
            "VALUES (?, '/tmp/fake.cer', '/tmp/fake.key', 'pass123', "
            "datetime('now'), datetime('now'))",
            (ISSUER_ID,),
        )
        conn.commit()
    finally:
        conn.close()


def _cleanup_sat_creds():
    """Remove SAT credentials for clean state."""
    conn = db()
    try:
        conn.execute("DELETE FROM sat_credentials WHERE issuer_id = ?", (ISSUER_ID,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Test: Unauthenticated access redirects to login
# ---------------------------------------------------------------------------
def test_should_redirect_to_login_when_not_authenticated():
    _seed()
    c = TestClient(app, follow_redirects=False)
    r = c.get("/onboarding")
    assert r.status_code == 302
    assert "/login" in r.headers["location"]


# ---------------------------------------------------------------------------
# Test: Step 1 shown for new user with PENDIENTE RFC
# ---------------------------------------------------------------------------
def test_should_show_step_1_when_rfc_is_pendiente():
    _seed()
    c = TestClient(app, follow_redirects=False)
    c.cookies.update(make_session_cookie(ISSUER_ID, USER_ID))
    r = c.get("/onboarding")
    assert r.status_code == 200
    body = r.text
    # Step 1 is active
    assert "Completa tu perfil fiscal" in body
    # Step indicator present
    assert "Datos fiscales" in body
    assert "Configurar SAT" in body
    assert "Primer factura" in body
    # Form fields
    assert 'name="rfc"' in body
    assert 'name="razon_social"' in body
    assert 'name="csrf_token"' in body


# ---------------------------------------------------------------------------
# Test: Step 2 shown when RFC is configured but no FIEL
# ---------------------------------------------------------------------------
def test_should_show_step_2_when_rfc_ok_but_no_fiel():
    _seed_with_rfc()
    _cleanup_sat_creds()
    c = TestClient(app, follow_redirects=False)
    c.cookies.update(make_session_cookie(ISSUER_ID, USER_ID))
    r = c.get("/onboarding")
    assert r.status_code == 200
    body = r.text
    assert "Conecta tu cuenta con el SAT" in body
    assert "/portal/config/sat" in body
    # Hint about security
    assert "cifrada" in body


# ---------------------------------------------------------------------------
# Test: Step 3 shown when RFC + FIEL configured
# ---------------------------------------------------------------------------
def test_should_show_step_3_when_fiel_configured():
    _seed_with_fiel()
    c = TestClient(app, follow_redirects=False)
    c.cookies.update(make_session_cookie(ISSUER_ID, USER_ID))
    r = c.get("/onboarding")
    assert r.status_code == 200
    body = r.text
    assert "Emite tu primera factura" in body
    assert "/portal/home" in body


# ---------------------------------------------------------------------------
# Test: POST onboarding saves fiscal data and redirects to step 2
# ---------------------------------------------------------------------------
def test_should_save_fiscal_data_and_redirect_to_step_2():
    _seed()
    _cleanup_sat_creds()
    c = TestClient(app, follow_redirects=False)
    c.cookies.update(make_session_cookie(ISSUER_ID, USER_ID))
    csrf = csrf_service.generate_csrf_token()
    r = c.post(
        "/onboarding",
        data={
            "rfc": "XAXX010101000",
            "razon_social": "Mi Empresa SA",
            "regimen_fiscal": "601",
            "cp": "06600",
            "csrf_token": csrf,
        },
    )
    assert r.status_code == 302
    assert "step=2" in r.headers["location"]
    # Verify data persisted
    rows = db_rows("SELECT rfc, razon_social FROM issuers WHERE id = ?", (ISSUER_ID,))
    assert rows[0]["rfc"] == "XAXX010101000"
    assert rows[0]["razon_social"] == "Mi Empresa SA"


# ---------------------------------------------------------------------------
# Test: POST onboarding with missing RFC redirects with error
# ---------------------------------------------------------------------------
def test_should_reject_post_when_rfc_missing():
    _seed()
    c = TestClient(app, follow_redirects=False)
    c.cookies.update(make_session_cookie(ISSUER_ID, USER_ID))
    csrf = csrf_service.generate_csrf_token()
    # Send whitespace-only RFC (passes Form validation but stripped to empty)
    r = c.post(
        "/onboarding",
        data={
            "rfc": "   ",
            "razon_social": "Test",
            "csrf_token": csrf,
        },
    )
    assert r.status_code == 302
    assert "error=required" in r.headers["location"]


# ---------------------------------------------------------------------------
# Test: POST onboarding without CSRF token is rejected
# ---------------------------------------------------------------------------
def test_should_reject_post_when_csrf_invalid():
    _seed()
    c = TestClient(app, follow_redirects=False)
    c.cookies.update(make_session_cookie(ISSUER_ID, USER_ID))
    r = c.post(
        "/onboarding",
        data={
            "rfc": "XAXX010101000",
            "razon_social": "Test Corp",
            "csrf_token": "bad-token",
        },
    )
    assert r.status_code == 302
    assert "error=invalid" in r.headers["location"]


# ---------------------------------------------------------------------------
# Test: Explicit step override via query param
# ---------------------------------------------------------------------------
def test_should_allow_step_override_via_query_param():
    _seed()
    c = TestClient(app, follow_redirects=False)
    c.cookies.update(make_session_cookie(ISSUER_ID, USER_ID))
    # Force step 2 even though user is on step 1
    r = c.get("/onboarding?step=2")
    assert r.status_code == 200
    assert "Conecta tu cuenta con el SAT" in r.text


# ---------------------------------------------------------------------------
# Test: Progress bar and step CSS classes are rendered
# ---------------------------------------------------------------------------
def test_should_render_progress_bar_and_step_classes():
    _seed_with_rfc()
    _cleanup_sat_creds()
    c = TestClient(app, follow_redirects=False)
    c.cookies.update(make_session_cookie(ISSUER_ID, USER_ID))
    r = c.get("/onboarding")
    assert r.status_code == 200
    body = r.text
    # Progress bar present
    assert "onboarding-progress" in body
    assert "onboarding-progress__bar" in body
    # Step 1 should be marked as done (RFC configured)
    assert "onboarding-steps__item--done" in body
    # Step 2 should be active
    assert "onboarding-steps__item--active" in body
    # Step 3 should be pending
    assert "onboarding-steps__item--pending" in body


# ---------------------------------------------------------------------------
# Test: Onboarding CSS is loaded
# ---------------------------------------------------------------------------
def test_should_include_onboarding_css():
    _seed()
    c = TestClient(app, follow_redirects=False)
    c.cookies.update(make_session_cookie(ISSUER_ID, USER_ID))
    r = c.get("/onboarding")
    assert r.status_code == 200
    assert "onboarding.css" in r.text
