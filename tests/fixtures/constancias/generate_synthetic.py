"""Generate synthetic Constancia de Situación Fiscal PDFs for parser testing.

Run: python tests/fixtures/constancias/generate_synthetic.py
"""
import io
import os

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


def _generate_constancia_pdf(data: dict) -> bytes:
    """Generate a synthetic SAT Constancia PDF mimicking real format."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    w, h = letter

    # Header
    c.setFont("Helvetica-Bold", 14)
    c.drawString(30 * mm, h - 25 * mm, "SERVICIO DE ADMINISTRACIÓN TRIBUTARIA")
    c.setFont("Helvetica", 10)
    c.drawString(30 * mm, h - 32 * mm, "Cédula de Identificación Fiscal")
    c.drawString(30 * mm, h - 37 * mm, "Constancia de Situación Fiscal")

    y = h - 50 * mm

    # RFC
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, "RFC:")
    c.setFont("Helvetica", 10)
    c.drawString(55 * mm, y, data["rfc"])
    y -= 7 * mm

    # CURP (only for PF)
    if data.get("curp"):
        c.setFont("Helvetica-Bold", 10)
        c.drawString(30 * mm, y, "CURP:")
        c.setFont("Helvetica", 10)
        c.drawString(55 * mm, y, data["curp"])
        y -= 7 * mm

    # Razón social / Nombre
    label = "Denominación o Razón Social:" if len(data["rfc"]) == 12 else "Nombre:"
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, label)
    c.setFont("Helvetica", 10)
    c.drawString(30 * mm, y - 5 * mm, data["razon_social"])
    y -= 14 * mm

    # Régimen fiscal
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, "Régimen Fiscal:")
    c.setFont("Helvetica", 10)
    c.drawString(30 * mm, y - 5 * mm, f"{data['regimen']} - {data['regimen_desc']}")
    y -= 14 * mm

    # Domicilio fiscal
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, "Domicilio Fiscal:")
    c.setFont("Helvetica", 10)
    c.drawString(30 * mm, y - 5 * mm, data["domicilio"])
    y -= 10 * mm

    # Código postal
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, "Código Postal:")
    c.setFont("Helvetica", 10)
    c.drawString(55 * mm, y, data["codigo_postal"])
    y -= 10 * mm

    # Obligaciones
    if data.get("obligaciones"):
        c.setFont("Helvetica-Bold", 10)
        c.drawString(30 * mm, y, "Obligaciones:")
        y -= 6 * mm
        c.setFont("Helvetica", 9)
        for ob in data["obligaciones"]:
            c.drawString(35 * mm, y, f"• {ob}")
            y -= 5 * mm

    c.save()
    return buf.getvalue()


FIXTURES = [
    {
        "filename": "constancia_pf_612.pdf",
        "rfc": "VEDA980101ABC",
        "curp": "VEDA980101HDFRRL01",
        "razon_social": "DAVID VENEGAS RAMIREZ",
        "regimen": "612",
        "regimen_desc": "Personas Físicas con Actividades Empresariales y Profesionales",
        "domicilio": "AV REFORMA 100, COL CENTRO, ALCALDIA CUAUHTEMOC, CDMX",
        "codigo_postal": "06000",
        "obligaciones": [
            "Declaración mensual de ISR por actividad empresarial",
            "Declaración mensual de IVA",
            "Declaración anual del ejercicio",
        ],
    },
    {
        "filename": "constancia_pm_601.pdf",
        "rfc": "TEST010101AB1",
        "curp": None,
        "razon_social": "EMPRESA PRUEBA SA DE CV",
        "regimen": "601",
        "regimen_desc": "General de Ley Personas Morales",
        "domicilio": "CALLE INDUSTRIA 50, COL INDUSTRIAL, MONTERREY, NL",
        "codigo_postal": "64000",
        "obligaciones": [
            "Declaración mensual de ISR personas morales",
            "Declaración mensual de IVA",
            "Declaración anual del ejercicio personas morales",
            "Retenciones de ISR por sueldos y salarios",
        ],
    },
    {
        "filename": "constancia_resico_626.pdf",
        "rfc": "LOGA850515XY9",
        "curp": "LOGA850515MDFRRL09",
        "razon_social": "ANA LOPEZ GARCIA",
        "regimen": "626",
        "regimen_desc": "Régimen Simplificado de Confianza",
        "domicilio": "CALLE HIDALGO 25, COL CENTRO, GUADALAJARA, JAL",
        "codigo_postal": "44100",
        "obligaciones": [
            "Declaración mensual RESICO",
            "Declaración anual del ejercicio",
        ],
    },
    {
        "filename": "constancia_multi_obligaciones.pdf",
        "rfc": "MUBE790320QR3",
        "curp": "MUBE790320HDFRRR05",
        "razon_social": "ERNESTO MURO BETANCOURT",
        "regimen": "612",
        "regimen_desc": "Personas Físicas con Actividades Empresariales y Profesionales",
        "domicilio": "AV INSURGENTES SUR 1000, COL DEL VALLE, BENITO JUAREZ, CDMX",
        "codigo_postal": "03100",
        "obligaciones": [
            "Declaración mensual de ISR por actividad empresarial",
            "Declaración mensual de IVA",
            "Declaración anual del ejercicio",
            "Retenciones de ISR por honorarios",
            "Retenciones de IVA",
            "Informativa de operaciones con terceros (DIOT)",
        ],
    },
    {
        "filename": "constancia_edge_case.pdf",
        "rfc": "XAXX010101000",
        "curp": None,
        "razon_social": "PUBLICO EN GENERAL",
        "regimen": "616",
        "regimen_desc": "Sin obligaciones fiscales",
        "domicilio": "",
        "codigo_postal": "00000",
        "obligaciones": [],
    },
]


if __name__ == "__main__":
    out_dir = os.path.dirname(os.path.abspath(__file__))
    for fx in FIXTURES:
        pdf_bytes = _generate_constancia_pdf(fx)
        path = os.path.join(out_dir, fx["filename"])
        with open(path, "wb") as f:
            f.write(pdf_bytes)
        print(f"Generated: {path} ({len(pdf_bytes)} bytes)")
    print(f"\nDone: {len(FIXTURES)} PDFs generated.")
