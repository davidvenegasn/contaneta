"""Tests for the tooltip system: macro rendering, CSS file, and base template inclusion."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEMPLATES_DIR = ROOT / "templates"
STATIC_DIR = ROOT / "static"


def test_should_have_tooltips_css_file():
    """Verify static/css/tooltips.css exists and contains core tooltip classes."""
    css_path = STATIC_DIR / "css" / "tooltips.css"
    assert css_path.exists(), f"Expected {css_path} to exist"
    content = css_path.read_text()
    assert ".help-tooltip" in content, "Expected .help-tooltip class in tooltips.css"
    assert "data-tooltip" in content, "Expected data-tooltip attribute selector"
    assert "data-tooltip-pos" in content, "Expected data-tooltip-pos for positioning"
    assert ".sr-tooltip-text" in content, "Expected .sr-tooltip-text for accessibility"


def test_should_include_tooltips_css_in_base_portal():
    """Verify base_portal.html links to tooltips.css."""
    base_html = (TEMPLATES_DIR / "base_portal.html").read_text()
    assert "tooltips.css" in base_html, (
        "Expected tooltips.css link in base_portal.html <head>"
    )


def test_should_render_tooltip_macro_with_correct_markup():
    """Verify the portal_tooltip Jinja2 macro produces correct HTML structure."""
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    # Render just the macro in isolation
    template_str = (
        '{% from "portal/_ui_components.html" import portal_tooltip %}'
        '{{ portal_tooltip("Texto de ayuda", position="top", id="test-tip") }}'
    )
    tmpl = env.from_string(template_str)
    html = tmpl.render()

    # Check CSS class
    assert 'class="help-tooltip"' in html, (
        "Expected help-tooltip class on tooltip element"
    )
    # Check data-tooltip attribute with the text
    assert 'data-tooltip="Texto de ayuda"' in html, (
        "Expected data-tooltip attribute with tooltip text"
    )
    # Check tabindex for keyboard access
    assert 'tabindex="0"' in html, (
        "Expected tabindex=0 for keyboard navigation"
    )
    # Check ARIA role
    assert 'role="img"' in html, (
        "Expected role=img on tooltip trigger"
    )
    # Check aria-describedby with matching id
    assert 'aria-describedby="test-tip"' in html, (
        "Expected aria-describedby pointing to sr text"
    )
    # Check screen reader text span
    assert 'id="test-tip"' in html, (
        "Expected id on sr-tooltip-text span"
    )
    assert 'class="sr-tooltip-text"' in html, (
        "Expected sr-tooltip-text class for screen reader text"
    )
    # The "?" text should be visible
    assert "?" in html, "Expected ? character as visible trigger"


def test_should_render_tooltip_with_bottom_position():
    """Verify position parameter produces data-tooltip-pos attribute."""
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template_str = (
        '{% from "portal/_ui_components.html" import portal_tooltip %}'
        '{{ portal_tooltip("Ayuda inferior", position="bottom") }}'
    )
    tmpl = env.from_string(template_str)
    html = tmpl.render()

    assert 'data-tooltip-pos="bottom"' in html, (
        "Expected data-tooltip-pos=bottom for bottom positioning"
    )


def test_should_omit_position_attr_for_top_default():
    """Verify top position (default) does not add data-tooltip-pos attribute."""
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template_str = (
        '{% from "portal/_ui_components.html" import portal_tooltip %}'
        '{{ portal_tooltip("Ayuda arriba") }}'
    )
    tmpl = env.from_string(template_str)
    html = tmpl.render()

    assert "data-tooltip-pos" not in html, (
        "Top position is default; should not emit data-tooltip-pos"
    )


def test_should_have_tooltips_in_datos_fiscales_template():
    """Verify portal_datos_fiscales.html includes tooltip macros for RFC, razon social, regimen."""
    content = (TEMPLATES_DIR / "portal_datos_fiscales.html").read_text()
    assert "portal_tooltip" in content, (
        "Expected portal_tooltip macro usage in datos fiscales"
    )
    assert "tooltip-rfc" in content, (
        "Expected tooltip-rfc id in datos fiscales template"
    )
    assert "tooltip-razon-social" in content, (
        "Expected tooltip-razon-social id in datos fiscales template"
    )
    assert "tooltip-regimen" in content, (
        "Expected tooltip-regimen id in datos fiscales template"
    )


def test_should_have_tooltips_in_dashboard_template():
    """Verify dashboard KPI partial includes tooltip macros for KPI metrics."""
    home_content = (TEMPLATES_DIR / "portal_home.html").read_text()
    assert "portal_tooltip" in home_content, (
        "Expected portal_tooltip macro import in home template"
    )
    content = (TEMPLATES_DIR / "partials" / "_dashboard_balance_v2.html").read_text()
    assert "tooltip-ingresos" in content, (
        "Expected tooltip-ingresos for income metric"
    )
    assert "tooltip-gastos" in content, (
        "Expected tooltip-gastos for expenses metric"
    )
    assert "tooltip-iva-cobrado" in content, (
        "Expected tooltip-iva-cobrado for IVA received metric"
    )
    assert "tooltip-iva-pagado" in content, (
        "Expected tooltip-iva-pagado for IVA paid metric"
    )


def test_should_have_tooltips_in_sat_config_template():
    """Verify portal_config_sat.html includes tooltip macros for FIEL fields."""
    content = (TEMPLATES_DIR / "portal_config_sat.html").read_text()
    assert "portal_tooltip" in content, (
        "Expected portal_tooltip macro usage in SAT config"
    )
    assert "tooltip-cer" in content, (
        "Expected tooltip-cer for certificate field"
    )
    assert "tooltip-key" in content, (
        "Expected tooltip-key for private key field"
    )
    assert "tooltip-fiel-pass" in content, (
        "Expected tooltip-fiel-pass for FIEL password field"
    )


def test_should_support_all_four_positions_in_css():
    """Verify tooltips.css has styles for top, bottom, left, and right positions."""
    content = (STATIC_DIR / "css" / "tooltips.css").read_text()
    for pos in ("top", "bottom", "left", "right"):
        assert f'[data-tooltip-pos="{pos}"]' in content, (
            f"Expected position style for {pos} in tooltips.css"
        )


def test_should_have_reduced_motion_in_tooltips_css():
    """Verify tooltips.css respects prefers-reduced-motion."""
    content = (STATIC_DIR / "css" / "tooltips.css").read_text()
    assert "prefers-reduced-motion" in content, (
        "Expected reduced motion media query in tooltips.css"
    )
