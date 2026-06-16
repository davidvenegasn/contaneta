"""Render email templates using Jinja2 from templates/emails/."""
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates" / "emails"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render(template_name: str, context: dict) -> tuple[str, str]:
    """Render an email template. Returns (html, text).

    Args:
        template_name: Template name without directory prefix (e.g. 'welcome').
        context: Variables to pass to the template.

    Returns:
        Tuple of (html_body, text_body).
    """
    html_template = _env.get_template(f"{template_name}.html")
    html = html_template.render(**context)
    try:
        text_template = _env.get_template(f"{template_name}.txt")
        text = text_template.render(**context)
    except Exception:
        # Fallback: derive plain text from HTML
        text = re.sub(r"<[^>]+>", "", html)
        text = re.sub(r"\s+\n", "\n", text).strip()
    return html, text
