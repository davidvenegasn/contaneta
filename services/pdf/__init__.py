"""PDF generation for CFDI 4.0 representación impresa.

Public API:
    render_cfdi_pdf(xml_path: str) -> bytes
        Parses a CFDI 4.0 XML, builds the Jinja context, renders the
        ContaNeta template via WeasyPrint, returns PDF bytes.

Complies with Anexo 20 RMF: includes Folio Fiscal, sellos (CFD + SAT),
cadena original del complemento de certificación digital del SAT, QR
con URL oficial de verificación, y leyenda de representación impresa.
"""
from .cfdi_renderer import render_cfdi_pdf

__all__ = ["render_cfdi_pdf"]
