"""Tests for Constancia de Situación Fiscal (Phase 8): parser + service + routes."""
import json

import pytest

from database import db
from services.constancia.parser import (
    _extract_codigo_postal,
    _extract_curp,
    _extract_razon_social,
    _extract_regimen,
    _extract_rfc,
)

ISSUER_ID = 99908
USER_ID = 99908


@pytest.fixture(scope="module", autouse=True)
def seed():
    """Create test issuer with constancia columns."""
    conn = db()
    # Ensure constancia columns exist
    try:
        conn.execute("SELECT constancia_pdf_path FROM issuers LIMIT 0")
    except Exception:
        for col in [
            "constancia_pdf_path TEXT",
            "constancia_uploaded_at TEXT",
            "constancia_extracted_json TEXT",
        ]:
            try:
                conn.execute(f"ALTER TABLE issuers ADD COLUMN {col}")
            except Exception:
                pass

    conn.execute(
        """INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, regimen_fiscal, fiscal_zip)
           VALUES (?, 'XCON010101AAA', 'Constancia Test SA de CV', 1, '601', '06600')""",
        (ISSUER_ID,),
    )
    conn.execute(
        """INSERT OR IGNORE INTO users (id, email, password_hash)
           VALUES (?, 'constancia@test.com', 'x')""",
        (USER_ID,),
    )
    conn.execute(
        """INSERT OR IGNORE INTO memberships (user_id, issuer_id, role)
           VALUES (?, ?, 'owner')""",
        (USER_ID, ISSUER_ID),
    )
    conn.commit()
    conn.close()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app import app
    from tests.helpers import make_session_cookie

    c = TestClient(app)
    cookies = make_session_cookie(ISSUER_ID, USER_ID)
    for k, v in cookies.items():
        c.cookies.set(k, v)
    return c


# ── Parser unit tests ──


def test_should_extract_rfc():
    """_extract_rfc should find RFC near label."""
    text = "RFC: XCON010101AAA\nNombre: Test SA"
    assert _extract_rfc(text) == "XCON010101AAA"


def test_should_extract_rfc_with_dot_notation():
    """_extract_rfc should handle R.F.C. format."""
    text = "R.F.C.: XABC020202BB9"
    assert _extract_rfc(text) == "XABC020202BB9"


def test_should_extract_curp():
    """_extract_curp should find CURP."""
    text = "CURP: GOVM850101HDFRLL09"
    assert _extract_curp(text) == "GOVM850101HDFRLL09"


def test_should_return_none_for_missing_curp():
    """_extract_curp should return None if no CURP found."""
    assert _extract_curp("No CURP in this text") is None


def test_should_extract_razon_social():
    """_extract_razon_social should find company name."""
    text = "Denominación: CONSTANCIA TEST SA DE CV\nRFC: XCON010101AAA"
    result = _extract_razon_social(text)
    assert result is not None
    assert "CONSTANCIA TEST" in result


def test_should_extract_regimen_by_code():
    """_extract_regimen should find 3-digit code."""
    text = "Régimen Fiscal: 601 General de Ley Personas Morales"
    assert _extract_regimen(text) == "601"


def test_should_extract_regimen_by_description():
    """_extract_regimen should find regime by description fallback."""
    text = "Régimen Simplificado de Confianza"
    assert _extract_regimen(text) == "626"


def test_should_extract_codigo_postal():
    """_extract_codigo_postal should find 5-digit CP."""
    text = "Código Postal: 06600"
    assert _extract_codigo_postal(text) == "06600"


def test_should_extract_cp_with_dot_notation():
    """_extract_codigo_postal should handle C.P. format."""
    text = "C.P. 03100"
    assert _extract_codigo_postal(text) == "03100"


def test_should_return_none_for_missing_cp():
    """_extract_codigo_postal should return None if no CP found."""
    assert _extract_codigo_postal("No postal code here") is None


# ── Service tests ──


def test_should_compare_and_find_diff():
    """process_constancia_upload should detect differences."""
    from services.constancia.service import _compare

    diff = []
    _compare(diff, "RFC", "XCON010101AAA", "XCON010101BBB")
    assert len(diff) == 1
    assert diff[0]["field"] == "RFC"
    assert diff[0]["current"] == "XCON010101AAA"
    assert diff[0]["extracted"] == "XCON010101BBB"


def test_should_not_diff_when_matching():
    """_compare should not add to diff when values match."""
    from services.constancia.service import _compare

    diff = []
    _compare(diff, "RFC", "XCON010101AAA", "XCON010101AAA")
    assert len(diff) == 0


def test_should_not_diff_when_extracted_is_none():
    """_compare should skip when extracted is None."""
    from services.constancia.service import _compare

    diff = []
    _compare(diff, "RFC", "XCON010101AAA", None)
    assert len(diff) == 0


def test_should_get_constancia_status_none_when_not_uploaded():
    """get_constancia_status should return None if no constancia uploaded."""
    from services.constancia.service import get_constancia_status

    result = get_constancia_status(ISSUER_ID)
    assert result is None


def test_should_apply_extracted_data_error_when_no_data():
    """apply_extracted_data should return error when no constancia processed."""
    from services.constancia.service import apply_extracted_data

    result = apply_extracted_data(ISSUER_ID)
    assert result["ok"] is False


# ── Route tests ──


def test_settings_should_load_with_constancia_section(client):
    """GET /portal/settings should include constancia upload section."""
    resp = client.get("/portal/settings")
    assert resp.status_code == 200
    assert "Constancia" in resp.text


def test_upload_should_reject_non_pdf(client):
    """POST /portal/settings/constancia/upload should reject non-PDF files."""
    from services.auth.csrf import generate_csrf_token

    token = generate_csrf_token()
    resp = client.post(
        "/portal/settings/constancia/upload",
        data={"csrf_token": token},
        files={"pdf_file": ("test.txt", b"not a pdf", "text/plain")},
    )
    assert resp.status_code == 200
    assert "Solo se aceptan archivos PDF" in resp.text
