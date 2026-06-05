"""Tests for the embedded manifesto page + status endpoint + CSD upload."""
import io
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_manifesto_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-manifesto"
os.environ.setdefault("FACTURAPI_SECRET_KEY", "sk_test_FAKE_FOR_UNIT_TESTS")

from starlette.testclient import TestClient

from app import app
from database import db
from services import issuers as issuers_service
from services.auth import users as users_service
from services.facturapi.orgs import FacturapiOrgsError
from tests.helpers import make_session_cookie

client = TestClient(app, raise_server_exceptions=False)


def _bootstrap_authed_issuer(rfc: str, razon_social: str = "Tenant Test SA") -> tuple[int, int]:
    """Create user + issuer + membership, return (user_id, issuer_id)."""
    issuer_id, _ = issuers_service.create_issuer_with_token(
        rfc=rfc, razon_social=razon_social, regimen_fiscal="616"
    )
    import secrets
    user = users_service.create_user(
        email=f"u_{secrets.token_hex(4)}@example.com",
        password_hash=users_service.hash_password("StrongPass123!"),
        name="Tester",
    )
    users_service.add_membership(user["id"], issuer_id, "owner")
    return user["id"], issuer_id


def test_status_returns_unprovisioned_when_org_id_missing():
    user_id, issuer_id = _bootstrap_authed_issuer("FFF010101FFF")
    cookies = make_session_cookie(issuer_id=issuer_id, user_id=user_id)
    r = client.get("/portal/api/facturapi/status", cookies=cookies)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["provisioned"] is False
    assert data["manifest_signed"] is False


def test_status_returns_provisioned_when_org_id_set():
    user_id, issuer_id = _bootstrap_authed_issuer("GGG010101GGG")
    conn = db()
    try:
        conn.execute(
            "UPDATE issuers SET facturapi_org_id = 'org_provisioned' WHERE id = ?",
            (issuer_id,),
        )
        conn.commit()
    finally:
        conn.close()

    cookies = make_session_cookie(issuer_id=issuer_id, user_id=user_id)
    r = client.get("/portal/api/facturapi/status", cookies=cookies)
    assert r.status_code == 200
    data = r.json()
    assert data["provisioned"] is True
    assert data["org_id"] == "org_provisioned"


def test_status_returns_manifest_signed_when_set():
    user_id, issuer_id = _bootstrap_authed_issuer("HHH010101HHH")
    conn = db()
    try:
        conn.execute(
            """UPDATE issuers
               SET facturapi_org_id = 'org_signed', manifest_signed_at = datetime('now')
               WHERE id = ?""",
            (issuer_id,),
        )
        conn.commit()
    finally:
        conn.close()
    cookies = make_session_cookie(issuer_id=issuer_id, user_id=user_id)
    r = client.get("/portal/api/facturapi/status", cookies=cookies)
    data = r.json()
    assert data["manifest_signed"] is True


def test_manifesto_page_shows_provisioning_when_org_id_missing():
    user_id, issuer_id = _bootstrap_authed_issuer("III010101III")
    cookies = make_session_cookie(issuer_id=issuer_id, user_id=user_id)
    r = client.get("/portal/setup/manifiesto", cookies=cookies)
    assert r.status_code == 200
    assert "Preparando tu cuenta" in r.text


def test_manifesto_page_shows_iframe_when_org_ready():
    user_id, issuer_id = _bootstrap_authed_issuer("JJJ010101JJJ")
    conn = db()
    try:
        conn.execute(
            "UPDATE issuers SET facturapi_org_id = 'org_ready_iframe' WHERE id = ?",
            (issuer_id,),
        )
        conn.commit()
    finally:
        conn.close()
    cookies = make_session_cookie(issuer_id=issuer_id, user_id=user_id)
    r = client.get("/portal/setup/manifiesto", cookies=cookies)
    assert r.status_code == 200
    assert "Paso 1 — Sube tu CSD" in r.text
    assert "embedded/manifiesto" in r.text
    assert "org_ready_iframe" in r.text


def test_manifesto_page_shows_done_when_signed():
    user_id, issuer_id = _bootstrap_authed_issuer("KKK010101KKK")
    conn = db()
    try:
        conn.execute(
            """UPDATE issuers
               SET facturapi_org_id = 'org_done', manifest_signed_at = datetime('now')
               WHERE id = ?""",
            (issuer_id,),
        )
        conn.commit()
    finally:
        conn.close()
    cookies = make_session_cookie(issuer_id=issuer_id, user_id=user_id)
    r = client.get("/portal/setup/manifiesto", cookies=cookies)
    assert r.status_code == 200
    assert "Listo para facturar" in r.text


def test_upload_csd_rejects_when_org_not_provisioned():
    user_id, issuer_id = _bootstrap_authed_issuer("LLL010101LLL")
    cookies = make_session_cookie(issuer_id=issuer_id, user_id=user_id)
    from services.auth import csrf as csrf_service
    csrf = csrf_service.generate_csrf_token()
    r = client.post(
        "/portal/api/facturapi/upload-csd",
        cookies=cookies,
        files={
            "cer_file": ("test.cer", b"x" * 200, "application/octet-stream"),
            "key_file": ("test.key", b"y" * 200, "application/octet-stream"),
        },
        data={"password": "pw", "csrf_token": csrf},
    )
    assert r.status_code == 409


def test_upload_csd_forwards_to_facturapi_on_success():
    user_id, issuer_id = _bootstrap_authed_issuer("MMM010101MMM")
    conn = db()
    try:
        conn.execute(
            "UPDATE issuers SET facturapi_org_id = 'org_csd_target' WHERE id = ?",
            (issuer_id,),
        )
        conn.commit()
    finally:
        conn.close()

    cookies = make_session_cookie(issuer_id=issuer_id, user_id=user_id)
    from services.auth import csrf as csrf_service
    csrf = csrf_service.generate_csrf_token()

    with patch("routers.portal.facturapi_setup.fpi_orgs.upload_csd") as mock_upload:
        mock_upload.return_value = {"id": "org_csd_target", "is_production_ready": True}
        r = client.post(
            "/portal/api/facturapi/upload-csd",
            cookies=cookies,
            files={
                "cer_file": ("real.cer", b"c" * 200, "application/octet-stream"),
                "key_file": ("real.key", b"k" * 200, "application/octet-stream"),
            },
            data={"password": "hunter2", "csrf_token": csrf},
        )
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        mock_upload.assert_called_once()
        kwargs = mock_upload.call_args.kwargs
        assert kwargs["password"] == "hunter2"


def test_upload_csd_surfaces_facturapi_error_message():
    user_id, issuer_id = _bootstrap_authed_issuer("NNN010101NNN")
    conn = db()
    try:
        conn.execute(
            "UPDATE issuers SET facturapi_org_id = 'org_csd_bad' WHERE id = ?",
            (issuer_id,),
        )
        conn.commit()
    finally:
        conn.close()

    cookies = make_session_cookie(issuer_id=issuer_id, user_id=user_id)
    from services.auth import csrf as csrf_service
    csrf = csrf_service.generate_csrf_token()

    with patch("routers.portal.facturapi_setup.fpi_orgs.upload_csd") as mock_upload:
        mock_upload.side_effect = FacturapiOrgsError(400, "El certificado no es un CSD.")
        r = client.post(
            "/portal/api/facturapi/upload-csd",
            cookies=cookies,
            files={
                "cer_file": ("bad.cer", b"c" * 200, "application/octet-stream"),
                "key_file": ("bad.key", b"k" * 200, "application/octet-stream"),
            },
            data={"password": "pw", "csrf_token": csrf},
        )
        assert r.status_code == 400
        body = r.json()
        assert body["ok"] is False
        assert "CSD" in body["error"]["message"]
