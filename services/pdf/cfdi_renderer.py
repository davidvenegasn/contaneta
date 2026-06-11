"""Render CFDI 4.0 PDF using WeasyPrint + the templates/pdf/cfdi.html template.

Public function: render_cfdi_pdf(xml_path) -> bytes.
"""
import base64
import io
import os
import sys
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

# WeasyPrint on macOS Apple Silicon can't auto-locate Homebrew dylibs
# (pango/cairo) because of SIP-restricted dyld envs. Setting this BEFORE
# importing weasyprint lets cffi.dlopen find them. No-op on Linux/prod.
if sys.platform == "darwin":
    os.environ.setdefault("DYLD_FALLBACK_LIBRARY_PATH", "/opt/homebrew/lib")

import qrcode  # noqa: E402
from jinja2 import Environment, FileSystemLoader, select_autoescape  # noqa: E402
from weasyprint import HTML  # noqa: E402

from .cfdi_parser import parse_cfdi  # noqa: E402

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_TEMPLATE_DIR = _PROJECT_ROOT / "templates" / "pdf"

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _sat_qr_url(uuid: str, rfc_emisor: str, rfc_receptor: str, total: str, sello_cfd: str) -> str:
    """Build the official SAT verification URL embedded in the QR (Anexo 20)."""
    try:
        total_dec = Decimal(str(total or "0"))
    except Exception:
        total_dec = Decimal("0")
    # 10 integer digits . 6 decimal digits — e.g. 0000000001.160000
    tt = f"{total_dec:017.6f}"
    fe = (sello_cfd or "")[-8:]
    return (
        "https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx"
        f"?id={uuid}&re={rfc_emisor}&rr={rfc_receptor}&tt={tt}&fe={quote(fe, safe='')}"
    )


def _qr_b64(data: str, box_size: int = 4) -> str:
    """Generate a QR code PNG and return its base64 representation."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=0,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def render_cfdi_pdf(xml_path: str) -> bytes:
    """Parse the XML, build context (with QR), render template, return PDF bytes.

    Raises:
        FileNotFoundError: if xml_path doesn't exist.
        ValueError: if XML is not a recognizable CFDI 4.0.
    """
    ctx = parse_cfdi(xml_path)

    qr_fields = ctx.pop("_qr_fields")
    qr_url = _sat_qr_url(
        uuid=qr_fields["uuid"],
        rfc_emisor=qr_fields["rfc_emisor"],
        rfc_receptor=qr_fields["rfc_receptor"],
        total=qr_fields["total"],
        sello_cfd=qr_fields["sello_cfd"],
    )
    ctx["qr_b64"] = _qr_b64(qr_url)

    template = _jinja_env.get_template("cfdi.html")
    html_str = template.render(**ctx)

    pdf_buf = io.BytesIO()
    HTML(string=html_str, base_url=str(_TEMPLATE_DIR)).write_pdf(pdf_buf)
    return pdf_buf.getvalue()
