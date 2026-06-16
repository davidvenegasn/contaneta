"""Tests for declaration PDF parser and upload service."""
import io
import uuid as uuid_mod

import pytest

from database import db, db_rows
from services.declarations.parser import (
    _classify_tipo,
    _extract_periodo,
    _normalize_date,
    extract_from_pdf,
)
from services.declarations.rfc_extractor import find_rfc_in_pdf
from services.declarations.service import (
    get_declaration_by_id,
    get_declarations_for_issuer,
    process_uploaded_pdf,
)

ISSUER_ID = 99920
USER_ID = 99920


@pytest.fixture(scope="module", autouse=True)
def seed():
    conn = db()
    conn.execute(
        "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
        "VALUES (?, 'DEC010101AAA', 'Declaration Test SA', 1, datetime('now'), datetime('now'))",
        (ISSUER_ID,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
        "VALUES (?, 'decl@test.local', 'x', datetime('now'))",
        (USER_ID,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role, created_at) "
        "VALUES (?, ?, 'owner', datetime('now'))",
        (USER_ID, ISSUER_ID),
    )
    conn.commit()
    conn.close()
    yield


def _make_mock_pdf(text: str) -> bytes:
    """Create a minimal PDF with the given text using reportlab if available, else fpdf2."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        y = 750
        for line in text.split("\n"):
            c.drawString(72, y, line)
            y -= 15
        c.save()
        return buf.getvalue()
    except ImportError:
        pass
    # Fallback: build a minimal PDF manually
    # This is a bare-minimum PDF that contains the text
    content = f"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
4 0 obj<</Length {len(text) + 30}>>
stream
BT /F1 12 Tf 72 750 Td ({text}) Tj ET
endstream
endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000266 00000 n
0000000206 00000 n
trailer<</Size 6/Root 1 0 R>>
startxref
{350 + len(text)}
%%EOF"""
    return content.encode("latin-1")


# ---- Parser unit tests ----

def test_should_classify_mensual_isr():
    assert _classify_tipo("Declaración mensual provisional ISR") == "mensual_isr"


def test_should_classify_mensual_iva():
    assert _classify_tipo("Pago definitivo del IVA mensual") == "mensual_iva"


def test_should_classify_anual():
    assert _classify_tipo("Declaración anual del ISR ejercicio 2025") == "anual_isr"


def test_should_classify_pago_referenciado():
    assert _classify_tipo("Captura de pago referenciado al SAT") == "pago_referenciado"


def test_should_return_none_for_unknown():
    assert _classify_tipo("Receta de cocina") is None


def test_should_extract_periodo_from_month_name():
    assert _extract_periodo("Periodo: Mayo de 2026") == "2026-05"


def test_should_extract_periodo_from_numeric():
    assert _extract_periodo("Fecha 03/2026 declarada") == "2026-03"


def test_should_normalize_date():
    assert _normalize_date("15/06/2026") == "2026-06-15"
    assert _normalize_date("1-3-2025") == "2025-03-01"


# ---- RFC extractor tests ----

def test_should_extract_rfc_near_label():
    text = "RFC: DEC010101AAA\nServicio de Administración Tributaria\nRFC: SAT970701NN3"
    assert find_rfc_in_pdf(text) == "DEC010101AAA"


def test_should_exclude_sat_rfc():
    text = "RFC SAT970701NN3 contribuyente"
    result = find_rfc_in_pdf(text)
    assert result != "SAT970701NN3"


def test_should_find_rfc_without_label():
    text = "Datos del contribuyente: Juan Perez DEC010101AAA Mexico"
    assert find_rfc_in_pdf(text) == "DEC010101AAA"


# ---- process_uploaded_pdf integration tests ----

def test_should_process_pdf_with_matching_rfc():
    """Upload a PDF containing our test RFC → should match and save."""
    text = (
        "RFC: DEC010101AAA\n"
        "Declaración mensual provisional ISR\n"
        "Periodo: Enero de 2026\n"
        "Total a pagar: $1,500.00\n"
        "Folio: ABC123456789\n"
    )
    pdf = _make_mock_pdf(text)
    result = process_uploaded_pdf(
        pdf_bytes=pdf,
        uploaded_by_user_id=USER_ID,
        filename="acuse_isr_enero.pdf",
    )
    assert result["status"] in ("saved", "duplicate")
    if result["status"] == "saved":
        assert result["matched_issuer_id"] == ISSUER_ID
        assert result["parse_confidence"] > 0


def test_should_reject_when_no_rfc_matches():
    """Upload a PDF with unknown RFC → should reject."""
    text = "RFC: ZZZ999999ZZ9\nDeclaracion mensual provisional ISR"
    pdf = _make_mock_pdf(text)
    result = process_uploaded_pdf(
        pdf_bytes=pdf,
        uploaded_by_user_id=USER_ID,
        filename="unknown.pdf",
    )
    assert result["status"] == "rejected"
    assert result["reason"] == "no_matching_issuer"


def test_should_detect_duplicate_by_sha():
    """Upload the same PDF twice → second should be duplicate."""
    text = f"RFC: DEC010101AAA\nUnique {uuid_mod.uuid4().hex}"
    pdf = _make_mock_pdf(text)
    r1 = process_uploaded_pdf(
        pdf_bytes=pdf,
        uploaded_by_user_id=USER_ID,
        filename="dup_test.pdf",
    )
    assert r1["status"] == "saved"
    r2 = process_uploaded_pdf(
        pdf_bytes=pdf,
        uploaded_by_user_id=USER_ID,
        filename="dup_test_copy.pdf",
    )
    assert r2["status"] == "duplicate"


def test_should_use_target_issuer_id_when_provided():
    """If target_issuer_id is given, skip RFC auto-detection."""
    text = "Some random text without RFC"
    pdf = _make_mock_pdf(text)
    result = process_uploaded_pdf(
        pdf_bytes=pdf,
        uploaded_by_user_id=USER_ID,
        filename="manual_assign.pdf",
        target_issuer_id=ISSUER_ID,
    )
    assert result["status"] in ("saved", "duplicate")


# ---- Service query tests ----

def test_should_get_declarations_for_issuer():
    declarations = get_declarations_for_issuer(ISSUER_ID)
    assert isinstance(declarations, list)


def test_should_get_declaration_by_id():
    # Insert one directly
    conn = db()
    cur = conn.execute(
        """INSERT INTO declarations (issuer_id, uploaded_by_user_id, tipo, pdf_path, pdf_sha256, status)
           VALUES (?, ?, 'test', '/tmp/test.pdf', ?, 'pending_review')""",
        (ISSUER_ID, USER_ID, uuid_mod.uuid4().hex),
    )
    did = cur.lastrowid
    conn.commit()
    conn.close()

    decl = get_declaration_by_id(did, ISSUER_ID)
    assert decl is not None
    assert decl["tipo"] == "test"

    # Wrong issuer should return None
    assert get_declaration_by_id(did, ISSUER_ID + 999) is None


# ---- Route tests ----

@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from app import app
    from tests.helpers import make_session_cookie
    cookies = make_session_cookie(issuer_id=ISSUER_ID, user_id=USER_ID)
    return TestClient(app, raise_server_exceptions=False, cookies=cookies)


def test_should_respond_200_contador_declaraciones(client):
    resp = client.get("/portal/contador/declaraciones")
    assert resp.status_code == 200


def test_should_respond_200_user_declaraciones(client):
    resp = client.get("/portal/declaraciones")
    assert resp.status_code == 200
