"""Tests for WCAG 2.1 AA accessibility features in the portal.

Verifies skip-nav link, ARIA landmarks, accessibility.css loading,
sr-only utility, reduced-motion support, and focus styles.

Note: portal HTML tests read the template source directly because the
test DB may not have all migrations applied (pre-existing migration
issue in 034_sat_sync_state_ops.sql). CSS tests read the file on disk.
The static asset test uses TestClient for the /static/ mount.
"""
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
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_a11y_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-a11y"

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402

CSS_PATH = ROOT / "static" / "css" / "accessibility.css"
BASE_PORTAL_TEMPLATE = ROOT / "templates" / "base_portal.html"
SIDEBAR_TEMPLATE = ROOT / "templates" / "components" / "portal_sidebar_unified.html"


@pytest.fixture(scope="module")
def client():
    """Test client for static file serving."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def portal_html():
    """Raw base_portal.html template source (not rendered)."""
    return BASE_PORTAL_TEMPLATE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sidebar_html():
    """Raw sidebar template source."""
    return SIDEBAR_TEMPLATE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css_content():
    """accessibility.css content."""
    return CSS_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Skip navigation link
# ---------------------------------------------------------------------------

def test_should_have_skip_nav_link_in_portal(portal_html):
    """Skip-nav link must be present and point to #portalMain."""
    assert 'class="skip-nav"' in portal_html
    assert 'href="#portalMain"' in portal_html


def test_should_have_skip_nav_with_spanish_text(portal_html):
    """Skip-nav link text must be in Spanish (user-facing)."""
    assert "Saltar al contenido" in portal_html


# ---------------------------------------------------------------------------
# 2. ARIA landmarks
# ---------------------------------------------------------------------------

def test_should_have_main_landmark(portal_html):
    """A <main> element with id='portalMain' must exist."""
    assert '<main' in portal_html
    assert 'id="portalMain"' in portal_html


def test_should_have_banner_landmark(portal_html):
    """The top bar must have role='banner' or be a <header>."""
    assert 'role="banner"' in portal_html


def test_should_have_navigation_landmark(sidebar_html):
    """Sidebar navigation must use <nav> with aria-label."""
    assert "<nav" in sidebar_html
    assert 'aria-label=' in sidebar_html


def test_should_have_contentinfo_landmark(portal_html):
    """Footer must have role='contentinfo'."""
    assert 'role="contentinfo"' in portal_html


def test_should_have_html_lang_attribute(portal_html):
    """Document must declare language for screen readers."""
    assert 'lang="es"' in portal_html


# ---------------------------------------------------------------------------
# 3. accessibility.css is loaded
# ---------------------------------------------------------------------------

def test_should_load_accessibility_css_in_template(portal_html):
    """The accessibility.css stylesheet must be linked in base_portal.html."""
    assert 'href="/static/css/accessibility.css"' in portal_html


def test_should_serve_accessibility_css(client):
    """The accessibility.css file must be served by the static file handler."""
    r = client.get("/static/css/accessibility.css")
    assert r.status_code == 200
    assert "text/css" in r.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# 4. sr-only class is defined
# ---------------------------------------------------------------------------

def test_should_define_sr_only_class(css_content):
    """The .sr-only class must be defined in accessibility.css."""
    assert ".sr-only" in css_content
    # Must use the standard visually-hidden technique
    assert "clip: rect(0" in css_content or "clip:rect(0" in css_content


def test_should_define_sr_only_focusable_class(css_content):
    """The .sr-only-focusable class must allow focused elements to be visible."""
    assert ".sr-only-focusable" in css_content


# ---------------------------------------------------------------------------
# 5. Reduced-motion media query
# ---------------------------------------------------------------------------

def test_should_have_reduced_motion_media_query(css_content):
    """accessibility.css must include a prefers-reduced-motion: reduce rule."""
    assert "prefers-reduced-motion: reduce" in css_content


def test_should_disable_animations_in_reduced_motion(css_content):
    """Reduced-motion rule must set animation/transition duration to near-zero."""
    assert "animation-duration: 0.01ms" in css_content
    assert "transition-duration: 0.01ms" in css_content


# ---------------------------------------------------------------------------
# 6. Focus styles are defined
# ---------------------------------------------------------------------------

def test_should_define_focus_visible_styles(css_content):
    """accessibility.css must define :focus-visible styles."""
    assert ":focus-visible" in css_content
    assert "outline:" in css_content or "outline :" in css_content


def test_should_define_focus_within_for_form_groups(css_content):
    """Form groups should have :focus-within styles."""
    assert ":focus-within" in css_content
    assert ".form-group:focus-within" in css_content


# ---------------------------------------------------------------------------
# 7. High-contrast mode support
# ---------------------------------------------------------------------------

def test_should_have_forced_colors_media_query(css_content):
    """accessibility.css must include forced-colors: active support."""
    assert "forced-colors: active" in css_content


# ---------------------------------------------------------------------------
# 8. Form accessibility attributes
# ---------------------------------------------------------------------------

def test_should_define_aria_invalid_styles(css_content):
    """accessibility.css must style [aria-invalid='true'] inputs."""
    assert '[aria-invalid="true"]' in css_content


def test_should_define_field_hint_class(css_content):
    """accessibility.css must define .field-hint for aria-describedby hints."""
    assert ".field-hint" in css_content


def test_should_define_field_error_class(css_content):
    """accessibility.css must define .field-error for error messages."""
    assert ".field-error" in css_content


# ---------------------------------------------------------------------------
# 9. CSS file exists and is non-empty
# ---------------------------------------------------------------------------

def test_accessibility_css_file_exists():
    """The accessibility.css file must exist on disk."""
    assert CSS_PATH.exists(), f"Expected {CSS_PATH} to exist"
    assert CSS_PATH.stat().st_size > 0, "accessibility.css must not be empty"


# ---------------------------------------------------------------------------
# 10. Existing accessibility features preserved
# ---------------------------------------------------------------------------

def test_should_have_skip_nav_styles_in_portal_css():
    """The portal.css must still contain the skip-nav styles."""
    portal_css = (ROOT / "static" / "css" / "portal.css").read_text(encoding="utf-8")
    assert ".skip-nav" in portal_css
    assert ".skip-nav:focus" in portal_css


def test_should_have_aria_hidden_on_decorative_icons(portal_html):
    """Decorative SVG icons must have aria-hidden='true'."""
    assert 'aria-hidden="true"' in portal_html
