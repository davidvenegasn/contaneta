"""Tests for the unified toast/notification system (Job 15).

Verifies that toast.js and toast.css are served correctly, that the toast
stack container and script/css references exist in portal pages, and that
the JS module exposes the expected public API.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_toast_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-toast"

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from database import db  # noqa: E402
from config import DB_PATH  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402
from tests.helpers import make_session_cookie  # noqa: E402

ISSUER_ID = 7701
USER_ID = 7701

client = TestClient(app)


def _ensure_seed():
    """Ensure minimal DB state for authenticated portal access."""
    apply_migrations(DB_PATH)
    conn = db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'TST7701', 'Issuer Toast Test', 1, datetime('now'), datetime('now'))",
            (ISSUER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
            "VALUES (?, 'toast_test@test.local', 'x', datetime('now'))",
            (USER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role, created_at) "
            "VALUES (?, ?, 'owner', datetime('now'))",
            (USER_ID, ISSUER_ID),
        )
        conn.commit()
    finally:
        conn.close()


# ─── Static file serving ───


def test_should_serve_toast_css():
    """toast.css should be served as a valid CSS file."""
    r = client.get("/static/css/toast.css")
    assert r.status_code == 200
    body = r.text
    assert ".toast-stack" in body
    assert ".toast__close" in body
    assert ".toast--success" in body
    assert ".toast--danger" in body
    assert ".toast--warning" in body
    assert ".toast--info" in body
    assert ".toast__progress" in body


def test_should_serve_toast_js():
    """toast.js should be served and contain the showToast public API."""
    r = client.get("/static/js/toast.js")
    assert r.status_code == 200
    body = r.text
    assert "window.showToast" in body
    assert "window.toastFromResponse" in body
    assert "window.portalToast" in body
    assert "window.toast" in body
    assert "convertFlashMessages" in body


def test_toast_js_should_define_close_button():
    """toast.js must render a close button with aria-label for accessibility."""
    r = client.get("/static/js/toast.js")
    body = r.text
    assert 'toast__close' in body
    assert 'aria-label="Cerrar"' in body


def test_toast_js_should_define_progress_bar():
    """toast.js must render a progress bar for auto-dismiss indicator."""
    r = client.get("/static/js/toast.js")
    body = r.text
    assert 'toast__progress' in body
    assert 'toastProgressShrink' in body


def test_toast_js_should_sanitize_error_messages():
    """toast.js must sanitize long or stack-trace error messages."""
    r = client.get("/static/js/toast.js")
    body = r.text
    assert "sanitizeErrorMessage" in body
    # Should truncate messages over 120 chars
    assert "120" in body


# ─── Portal page integration ───


def test_should_include_toast_css_in_portal_page():
    """Portal pages should reference toast.css in the head."""
    _ensure_seed()
    cookies = make_session_cookie(ISSUER_ID, USER_ID)
    r = client.get("/portal/home", cookies=cookies)
    assert r.status_code == 200
    assert '/static/css/toast.css' in r.text


def test_should_include_toast_js_in_portal_page():
    """Portal pages should load toast.js before ui.js."""
    _ensure_seed()
    cookies = make_session_cookie(ISSUER_ID, USER_ID)
    r = client.get("/portal/home", cookies=cookies)
    body = r.text
    assert '/static/js/toast.js' in body
    # toast.js must appear before ui.js in the HTML
    toast_pos = body.find('/static/js/toast.js')
    ui_pos = body.find('/static/js/ui.js')
    assert toast_pos < ui_pos, "toast.js must load before ui.js"


def test_should_have_toast_stack_container():
    """Portal pages should have the #toastStack container for toast rendering."""
    _ensure_seed()
    cookies = make_session_cookie(ISSUER_ID, USER_ID)
    r = client.get("/portal/home", cookies=cookies)
    assert 'id="toastStack"' in r.text
    assert 'class="toast-stack"' in r.text


# ─── CSS content validation ───


def test_toast_css_should_have_nightmode_overrides():
    """toast.css must include nightmode/dark-mode overrides."""
    r = client.get("/static/css/toast.css")
    body = r.text
    assert "html.nightmode .toast" in body


def test_toast_css_should_have_mobile_responsive_rules():
    """toast.css must include mobile-responsive layout (bottom on mobile)."""
    r = client.get("/static/css/toast.css")
    body = r.text
    assert "max-width: 768px" in body
    assert "column-reverse" in body


def test_toast_css_should_have_reduced_motion():
    """toast.css must respect prefers-reduced-motion for accessibility."""
    r = client.get("/static/css/toast.css")
    body = r.text
    assert "prefers-reduced-motion" in body


# ─── JS module structure ───


def test_toast_js_should_have_type_mapping():
    """toast.js should map 'error' to 'danger' and 'warn' to 'warning'."""
    r = client.get("/static/js/toast.js")
    body = r.text
    assert "error: 'danger'" in body
    assert "warn: 'warning'" in body


def test_toast_js_should_have_flash_conversion():
    """toast.js should auto-convert [data-flash-message] elements to toasts."""
    r = client.get("/static/js/toast.js")
    body = r.text
    assert "data-flash-message" in body
    assert "data-flash-type" in body
    assert "convertFlashMessages" in body
