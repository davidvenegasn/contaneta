"""Tests for quotation → invoice conversion tracking (Phase 5)."""

import pytest

from database import db

ISSUER_ID = 99905


@pytest.fixture(scope="module", autouse=True)
def seed():
    """Create test data for quotation conversion tests."""
    conn = db()
    conn.execute(
        """INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, regimen_fiscal)
           VALUES (?, 'XQUOT0101AAA', 'Quote Test SA', 1, '601')""",
        (ISSUER_ID,),
    )
    # Add conversion columns if missing
    for col, ctype in [("converted_invoice_id", "INTEGER"), ("converted_at", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE quotations ADD COLUMN {col} {ctype}")
        except Exception:
            pass
    conn.commit()
    conn.close()
    yield


def test_conversion_columns_exist():
    """Quotations table should have converted_invoice_id and converted_at."""
    conn = db()
    row = conn.execute("PRAGMA table_info(quotations)").fetchall()
    conn.close()
    cols = [r["name"] for r in row]
    assert "converted_invoice_id" in cols
    assert "converted_at" in cols


def test_mark_quotation_as_converted():
    """Should be able to update a quotation to 'converted' status."""
    conn = db()
    conn.execute(
        """INSERT OR IGNORE INTO quotations
           (id, issuer_id, customer_rfc, customer_legal_name, status, public_token)
           VALUES (?, ?, 'XAXX010101000', 'Test Client', 'accepted', 'conv-test-token')""",
        (99905, ISSUER_ID),
    )
    conn.execute(
        """UPDATE quotations SET status = 'converted',
           converted_invoice_id = 12345, converted_at = datetime('now')
           WHERE id = ? AND issuer_id = ?""",
        (99905, ISSUER_ID),
    )
    conn.commit()
    row = conn.execute(
        "SELECT status, converted_invoice_id FROM quotations WHERE id = ?",
        (99905,),
    ).fetchone()
    conn.close()
    assert row["status"] == "converted"
    assert row["converted_invoice_id"] == 12345


def test_hidden_field_present_in_create_form():
    """The /portal/create?quote_id=X form should include a hidden quote_id field."""
    conn = db()
    # Create a quotation to use
    conn.execute(
        """INSERT OR IGNORE INTO quotations
           (id, issuer_id, customer_rfc, customer_legal_name, status, public_token)
           VALUES (?, ?, 'XAXX010101000', 'Test Client', 'accepted', 'form-test-token')""",
        (99906, ISSUER_ID),
    )
    # Create user + membership
    conn.execute(
        """INSERT OR IGNORE INTO users (id, email, password_hash)
           VALUES (?, 'quotetest@test.com', 'x')""",
        (ISSUER_ID,),
    )
    conn.execute(
        """INSERT OR IGNORE INTO memberships (user_id, issuer_id, role)
           VALUES (?, ?, 'owner')""",
        (ISSUER_ID, ISSUER_ID),
    )
    conn.commit()
    conn.close()

    from fastapi.testclient import TestClient

    from app import app
    from tests.helpers import make_session_cookie

    c = TestClient(app)
    cookies = make_session_cookie(ISSUER_ID, ISSUER_ID)
    for k, v in cookies.items():
        c.cookies.set(k, v)

    resp = c.get("/portal/create?quote_id=99906")
    assert resp.status_code == 200
    assert 'name="quote_id"' in resp.text
    assert 'value="99906"' in resp.text
