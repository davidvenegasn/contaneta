"""Tests for link preloading on hover feature."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_preload_script_exists():
    """portal_preload.js must exist in static/js/."""
    js = ROOT / "static" / "js" / "portal_preload.js"
    assert js.exists(), f"Missing {js}"
    content = js.read_text()
    assert "prefetch" in content
    assert "debounce" in content.lower() or "DEBOUNCE_MS" in content


def test_preload_script_referenced_in_base_template():
    """base_portal.html must load portal_preload.js with defer."""
    tpl = ROOT / "templates" / "base_portal.html"
    content = tpl.read_text()
    assert "portal_preload.js" in content
    # Should be loaded with defer
    match = re.search(r'<script[^>]*portal_preload\.js[^>]*>', content)
    assert match, "script tag for portal_preload.js not found"
    assert "defer" in match.group(0)


def test_reduced_motion_respected_globally():
    """portal.css must have a prefers-reduced-motion block that kills animations."""
    css = ROOT / "static" / "css" / "portal.css"
    content = css.read_text()
    assert "prefers-reduced-motion: reduce" in content
    assert "animation-duration: 0.01ms" in content or "animation: none" in content


def test_logout_link_has_no_preload():
    """Logout form must have data-no-preload to prevent prefetching /logout."""
    tpl = ROOT / "templates" / "base_portal.html"
    content = tpl.read_text()
    logout_match = re.search(r'<form[^>]*action="/logout"[^>]*>', content)
    assert logout_match, "Logout form not found"
    assert "data-no-preload" in logout_match.group(0)


def test_preload_script_respects_save_data():
    """portal_preload.js must check navigator.connection.saveData."""
    js = ROOT / "static" / "js" / "portal_preload.js"
    content = js.read_text()
    assert "saveData" in content
    assert "effectiveType" in content
