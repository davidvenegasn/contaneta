"""Tests for View Transitions + link preloading on hover feature."""
import os
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


def test_view_transitions_css_present():
    """portal.css must include @view-transition and keyframes."""
    css = ROOT / "static" / "css" / "portal.css"
    content = css.read_text()
    assert "@view-transition" in content
    assert "portal-vt-fade-out" in content
    assert "portal-vt-fade-in" in content
    assert "::view-transition-old(root)" in content
    assert "::view-transition-new(root)" in content


def test_reduced_motion_disables_view_transitions():
    """View Transitions must be disabled under prefers-reduced-motion: reduce."""
    css = ROOT / "static" / "css" / "portal.css"
    content = css.read_text()
    # Find the reduced-motion block that targets view transitions
    # Should contain animation: none for view-transition pseudo-elements
    pattern = r'@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{[^}]*::view-transition'
    assert re.search(pattern, content), (
        "Expected a prefers-reduced-motion block that disables view transitions"
    )


def test_logout_link_has_no_preload():
    """Logout form must have data-no-preload to prevent prefetching /logout."""
    tpl = ROOT / "templates" / "base_portal.html"
    content = tpl.read_text()
    # Find the logout form and verify data-no-preload
    logout_match = re.search(r'<form[^>]*action="/logout"[^>]*>', content)
    assert logout_match, "Logout form not found"
    assert "data-no-preload" in logout_match.group(0)


def test_preload_script_respects_save_data():
    """portal_preload.js must check navigator.connection.saveData."""
    js = ROOT / "static" / "js" / "portal_preload.js"
    content = js.read_text()
    assert "saveData" in content
    assert "effectiveType" in content
