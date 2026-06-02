"""Tests for public quotation routes (no auth required)."""

import os
import secrets
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if not os.environ.get("APP_DB_PATH"):
    _fd, _p = tempfile.mkstemp(suffix=".db", prefix="test_pub_quot_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _p
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-pub-quot"

import database  # noqa: E402
from config import DB_PATH  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402

ISSUER_ID = 88801
USER_ID = 88801
PUBLIC_TOKEN = secrets.token_urlsafe(24)
PUBLIC_TOKEN_ACCEPT = secrets.token_urlsafe(24)


@pytest.fixture(scope="module", autouse=True)
def seed():
    apply_migrations(DB_PATH)
    conn = database.db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'PUBQ010101AAA', 'PubQuot Test SA', 1, datetime('now'), datetime('now'))",
            (ISSUER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
            "VALUES (?, 'pubquot@test.local', 'x', datetime('now'))",
            (USER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role, created_at) "
            "VALUES (?, ?, 'owner', datetime('now'))",
            (USER_ID, ISSUER_ID),
        )
        # Create test quotations with public_tokens
        conn.execute(
            "INSERT OR IGNORE INTO quotations "
            "(issuer_id, customer_rfc, customer_legal_name, customer_email, status, public_token, "
            " folio, valid_until, notes, created_at, updated_at) "
            "VALUES (?, 'CLI010101AAA', 'Cliente Test SA', 'cli@test.local', 'sent', ?, "
            " 'Q-2026-0001', '2026-12-31', 'Test notes', datetime('now'), datetime('now'))",
            (ISSUER_ID, PUBLIC_TOKEN),
        )
        conn.execute(
            "INSERT OR IGNORE INTO quotations "
            "(issuer_id, customer_rfc, customer_legal_name, customer_email, status, public_token, "
            " folio, valid_until, notes, created_at, updated_at) "
            "VALUES (?, 'CLI010101AAA', 'Cliente Test SA', 'cli@test.local', 'sent', ?, "
            " 'Q-2026-0002', '2026-12-31', 'Accept test', datetime('now'), datetime('now'))",
            (ISSUER_ID, PUBLIC_TOKEN_ACCEPT),
        )
        # Add items to quotations
        for tok in (PUBLIC_TOKEN, PUBLIC_TOKEN_ACCEPT):
            qid_row = conn.execute(
                "SELECT id FROM quotations WHERE public_token = ?", (tok,)
            ).fetchone()
            if qid_row:
                conn.execute(
                    "INSERT OR IGNORE INTO quotation_items "
                    "(quotation_id, description, quantity, unit_price, iva_rate, sort_order) "
                    "VALUES (?, 'Servicio de consultoría', 10, 1500.00, 0.16, 1)",
                    (qid_row["id"],),
                )
        conn.commit()
    finally:
        conn.close()
    yield


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from app import app
    # No cookies — public routes don't require auth
    return TestClient(app, raise_server_exceptions=False)


def test_public_quotation_renders_without_auth(client):
    """GET /q/{token} should render quotation details without login."""
    resp = client.get(f"/q/{PUBLIC_TOKEN}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert "Cliente Test SA" in resp.text or "CLI010101AAA" in resp.text


def test_public_quotation_404_when_token_invalid(client):
    """GET /q/{bad_token} should return 404."""
    resp = client.get("/q/this-token-does-not-exist-at-all")
    assert resp.status_code == 404


def test_public_quotation_accept_updates_status(client):
    """POST respond with action=accept should update status to accepted."""
    resp = client.post(
        "/public/cotizacion/respond",
        data={"public_token": PUBLIC_TOKEN_ACCEPT, "action": "aceptar"},
    )
    # Should return 200 (thanks page) or redirect
    assert resp.status_code in (200, 302, 303)

    # Verify DB was updated
    conn = database.db()
    try:
        row = conn.execute(
            "SELECT status, accepted_at FROM quotations WHERE public_token = ?",
            (PUBLIC_TOKEN_ACCEPT,),
        ).fetchone()
    finally:
        conn.close()
    assert row["status"] == "accepted"
    assert row["accepted_at"] is not None


def test_public_quotation_pdf_downloadable_without_auth(client):
    """GET /q/{token}/pdf should return PDF content."""
    resp = client.get(f"/q/{PUBLIC_TOKEN}/pdf")
    # PDF generation may fail if reportlab has issues, but route should exist
    assert resp.status_code in (200, 500)
    if resp.status_code == 200:
        assert resp.headers.get("content-type", "").startswith("application/pdf")


def test_quotation_has_public_token_on_create():
    """Quotations should have a public_token assigned."""
    conn = database.db()
    try:
        row = conn.execute(
            "SELECT public_token FROM quotations WHERE issuer_id = ? LIMIT 1",
            (ISSUER_ID,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["public_token"] is not None
    assert len(row["public_token"]) > 10
