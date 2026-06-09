"""Tests for the unified onboarding page + status + CSD upload + onboard endpoints."""
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
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_onboard_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-onboard"
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


# ── Status endpoint ──────────────────────────────────────────────────────


def test_status_returns_unprovisioned_when_org_id_missing():
    user_id, issuer_id = _bootstrap_authed_issuer("FFF010101FFF")
    cookies = make_session_cookie(issuer_id=issuer_id, user_id=user_id)
    r = client.get("/portal/api/facturapi/status", cookies=cookies)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["provisioned"] is False
    assert data["manifest_signed"] is False
    assert data["csd_uploaded"] is False
    assert data["onboarding_completed"] is False


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


def test_status_returns_completed_when_all_set():
    user_id, issuer_id = _bootstrap_authed_issuer("HHC010101HHC")
    conn = db()
    try:
        conn.execute(
            """UPDATE issuers
               SET facturapi_org_id = 'org_completed',
                   manifest_signed_at = datetime('now'),
                   csd_uploaded_at = datetime('now'),
                   onboarding_completed_at = datetime('now')
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
    assert data["csd_uploaded"] is True
    assert data["onboarding_completed"] is True


# ── Onboarding page (new URL) ────────────────────────────────────────────


def test_onboarding_page_shows_provisioning_when_org_id_missing():
    user_id, issuer_id = _bootstrap_authed_issuer("III010101III")
    cookies = make_session_cookie(issuer_id=issuer_id, user_id=user_id)
    r = client.get("/portal/setup/credenciales", cookies=cookies)
    assert r.status_code == 200
    assert "Preparando tu cuenta" in r.text


def test_onboarding_page_shows_form_when_org_ready():
    user_id, issuer_id = _bootstrap_authed_issuer("JJJ010101JJJ")
    conn = db()
    try:
        conn.execute(
            "UPDATE issuers SET facturapi_org_id = 'org_ready_form' WHERE id = ?",
            (issuer_id,),
        )
        conn.commit()
    finally:
        conn.close()
    cookies = make_session_cookie(issuer_id=issuer_id, user_id=user_id)
    r = client.get("/portal/setup/credenciales", cookies=cookies)
    assert r.status_code == 200
    assert "FIEL" in r.text
    assert "CSD" in r.text
    assert "CIEC" in r.text  # new optional section
    assert "Conectar y empezar a facturar" in r.text


def test_onboarding_page_shows_done_when_completed():
    user_id, issuer_id = _bootstrap_authed_issuer("KKK010101KKK")
    conn = db()
    try:
        conn.execute(
            """UPDATE issuers
               SET facturapi_org_id = 'org_done',
                   manifest_signed_at = datetime('now'),
                   csd_uploaded_at = datetime('now'),
                   onboarding_completed_at = datetime('now')
               WHERE id = ?""",
            (issuer_id,),
        )
        conn.commit()
    finally:
        conn.close()
    cookies = make_session_cookie(issuer_id=issuer_id, user_id=user_id)
    r = client.get("/portal/setup/credenciales", cookies=cookies)
    assert r.status_code == 200
    assert "Listo para facturar" in r.text


def test_legacy_manifiesto_url_redirects_to_credenciales():
    user_id, issuer_id = _bootstrap_authed_issuer("LEG010101LEG")
    cookies = make_session_cookie(issuer_id=issuer_id, user_id=user_id)
    r = client.get("/portal/setup/manifiesto", cookies=cookies, follow_redirects=False)
    assert r.status_code == 302
    assert "/portal/setup/credenciales" in r.headers["location"]


# ── Legacy upload-csd endpoint (preserved for compat) ─────────────────────


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


def test_upload_csd_marks_csd_uploaded_at_on_success():
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
        assert r.status_code == 200

    conn = db()
    try:
        row = conn.execute("SELECT csd_uploaded_at FROM issuers WHERE id = ?", (issuer_id,)).fetchone()
        assert row["csd_uploaded_at"] is not None
    finally:
        conn.close()


# ── New unified onboard endpoint ─────────────────────────────────────────


def _post_onboard(cookies, *, fiel_cer=b"c" * 200, fiel_key=b"k" * 200, fiel_pw="fielpw",
                  csd_cer=b"c" * 200, csd_key=b"k" * 200, csd_pw="csdpw"):
    from services.auth import csrf as csrf_service
    csrf = csrf_service.generate_csrf_token()
    return client.post(
        "/portal/api/facturapi/onboard",
        cookies=cookies,
        files={
            "fiel_cer": ("fiel.cer", fiel_cer, "application/octet-stream"),
            "fiel_key": ("fiel.key", fiel_key, "application/octet-stream"),
            "csd_cer": ("csd.cer", csd_cer, "application/octet-stream"),
            "csd_key": ("csd.key", csd_key, "application/octet-stream"),
        },
        data={"fiel_password": fiel_pw, "csd_password": csd_pw, "csrf_token": csrf},
    )


def test_onboard_rejects_when_org_not_provisioned():
    user_id, issuer_id = _bootstrap_authed_issuer("NNN010101NNN")
    cookies = make_session_cookie(issuer_id=issuer_id, user_id=user_id)
    r = _post_onboard(cookies)
    assert r.status_code == 409


def test_onboard_signs_manifesto_then_uploads_csd_on_success():
    user_id, issuer_id = _bootstrap_authed_issuer("OOO010101OOO")
    conn = db()
    try:
        conn.execute(
            "UPDATE issuers SET facturapi_org_id = 'org_onboard_ok' WHERE id = ?",
            (issuer_id,),
        )
        conn.commit()
    finally:
        conn.close()

    cookies = make_session_cookie(issuer_id=issuer_id, user_id=user_id)

    with patch("routers.portal.facturapi_setup.fpi_orgs.sign_manifesto") as mock_sign, \
         patch("routers.portal.facturapi_setup.fpi_orgs.upload_csd") as mock_csd:
        mock_sign.return_value = {"id": "org_onboard_ok"}
        mock_csd.return_value = {"id": "org_onboard_ok", "is_production_ready": True}
        r = _post_onboard(cookies)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["manifest_signed"] is True
        assert body["csd_uploaded"] is True
        assert body["onboarding_completed"] is True

    conn = db()
    try:
        row = conn.execute(
            "SELECT manifest_signed_at, csd_uploaded_at, onboarding_completed_at FROM issuers WHERE id = ?",
            (issuer_id,),
        ).fetchone()
        assert row["manifest_signed_at"] is not None
        assert row["csd_uploaded_at"] is not None
        assert row["onboarding_completed_at"] is not None
    finally:
        conn.close()


def test_onboard_returns_manifesto_error_and_skips_csd():
    user_id, issuer_id = _bootstrap_authed_issuer("PPP010101PPP")
    conn = db()
    try:
        conn.execute(
            "UPDATE issuers SET facturapi_org_id = 'org_onboard_fail' WHERE id = ?",
            (issuer_id,),
        )
        conn.commit()
    finally:
        conn.close()

    cookies = make_session_cookie(issuer_id=issuer_id, user_id=user_id)

    with patch("routers.portal.facturapi_setup.fpi_orgs.sign_manifesto") as mock_sign, \
         patch("routers.portal.facturapi_setup.fpi_orgs.upload_csd") as mock_csd:
        mock_sign.side_effect = FacturapiOrgsError(400, "La contraseña es incorrecta")
        r = _post_onboard(cookies)
        assert r.status_code == 400
        body = r.json()
        assert body["ok"] is False
        assert body["step"] == "manifesto"
        assert "contraseña" in body["error"]["message"].lower()
        mock_csd.assert_not_called()  # CSD must NOT be attempted if manifesto failed


def test_upload_fiel_alone_signs_manifesto():
    """Per-card endpoint: FIEL upload signs manifesto via headless endpoint."""
    user_id, issuer_id = _bootstrap_authed_issuer("FFL010101FFL")
    conn = db()
    try:
        conn.execute(
            "UPDATE issuers SET facturapi_org_id = 'org_fiel_only' WHERE id = ?",
            (issuer_id,),
        )
        conn.commit()
    finally:
        conn.close()

    cookies = make_session_cookie(issuer_id=issuer_id, user_id=user_id)
    from services.auth import csrf as csrf_service
    csrf = csrf_service.generate_csrf_token()

    with patch("routers.portal.facturapi_setup.fpi_orgs.sign_manifesto") as mock_sign:
        mock_sign.return_value = {"id": "org_fiel_only"}
        r = client.post(
            "/portal/api/facturapi/upload-fiel",
            cookies=cookies,
            files={
                "cer_file": ("fiel.cer", b"c" * 200, "application/octet-stream"),
                "key_file": ("fiel.key", b"k" * 200, "application/octet-stream"),
            },
            data={"password": "fpw", "csrf_token": csrf},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True

    conn = db()
    try:
        row = conn.execute(
            "SELECT manifest_signed_at FROM issuers WHERE id = ?",
            (issuer_id,),
        ).fetchone()
        assert row["manifest_signed_at"] is not None
    finally:
        conn.close()


def test_save_ciec_alone_persists_encrypted():
    """Per-card endpoint: CIEC password gets persisted encrypted."""
    user_id, issuer_id = _bootstrap_authed_issuer("CIC010101CIC")
    cookies = make_session_cookie(issuer_id=issuer_id, user_id=user_id)
    from services.auth import csrf as csrf_service
    csrf = csrf_service.generate_csrf_token()

    r = client.post(
        "/portal/api/facturapi/save-ciec",
        cookies=cookies,
        data={"ciec_password": "CiecSecret2026!", "csrf_token": csrf},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True

    conn = db()
    try:
        row = conn.execute(
            "SELECT ciec_password_encrypted FROM sat_credentials WHERE issuer_id = ?",
            (issuer_id,),
        ).fetchone()
        assert row is not None
        assert row["ciec_password_encrypted"].startswith("enc:")
        assert "CiecSecret2026" not in row["ciec_password_encrypted"]
    finally:
        conn.close()


def test_onboard_saves_ciec_when_provided():
    """Optional CIEC field should be encrypted and persisted to sat_credentials."""
    user_id, issuer_id = _bootstrap_authed_issuer("RRR010101RRR")
    conn = db()
    try:
        conn.execute(
            "UPDATE issuers SET facturapi_org_id = 'org_ciec' WHERE id = ?",
            (issuer_id,),
        )
        conn.commit()
    finally:
        conn.close()

    cookies = make_session_cookie(issuer_id=issuer_id, user_id=user_id)
    from services.auth import csrf as csrf_service
    csrf = csrf_service.generate_csrf_token()

    with patch("routers.portal.facturapi_setup.fpi_orgs.sign_manifesto") as mock_sign, \
         patch("routers.portal.facturapi_setup.fpi_orgs.upload_csd") as mock_csd:
        mock_sign.return_value = {"id": "org_ciec"}
        mock_csd.return_value = {"id": "org_ciec"}
        r = client.post(
            "/portal/api/facturapi/onboard",
            cookies=cookies,
            files={
                "fiel_cer": ("fiel.cer", b"c" * 200, "application/octet-stream"),
                "fiel_key": ("fiel.key", b"k" * 200, "application/octet-stream"),
                "csd_cer": ("csd.cer", b"c" * 200, "application/octet-stream"),
                "csd_key": ("csd.key", b"k" * 200, "application/octet-stream"),
            },
            data={
                "fiel_password": "fpw",
                "csd_password": "cpw",
                "ciec_password": "MyCIECSecret2026!",
                "csrf_token": csrf,
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ciec_saved"] is True

    conn = db()
    try:
        row = conn.execute(
            "SELECT ciec_password_encrypted FROM sat_credentials WHERE issuer_id = ?",
            (issuer_id,),
        ).fetchone()
        assert row is not None
        enc = row["ciec_password_encrypted"]
        assert enc, "CIEC password not persisted"
        # Encrypted blobs from crypto_at_rest.encrypt_text are prefixed with 'enc:'
        assert enc.startswith("enc:"), f"expected 'enc:' prefix, got {enc[:20]!r}"
        # And of course must NOT contain the plaintext
        assert "MyCIECSecret2026" not in enc
    finally:
        conn.close()


def test_onboard_csd_error_after_manifesto_success_keeps_partial_state():
    user_id, issuer_id = _bootstrap_authed_issuer("QQQ010101QQQ")
    conn = db()
    try:
        conn.execute(
            "UPDATE issuers SET facturapi_org_id = 'org_partial' WHERE id = ?",
            (issuer_id,),
        )
        conn.commit()
    finally:
        conn.close()

    cookies = make_session_cookie(issuer_id=issuer_id, user_id=user_id)

    with patch("routers.portal.facturapi_setup.fpi_orgs.sign_manifesto") as mock_sign, \
         patch("routers.portal.facturapi_setup.fpi_orgs.upload_csd") as mock_csd:
        mock_sign.return_value = {"id": "org_partial"}
        mock_csd.side_effect = FacturapiOrgsError(400, "El certificado no es un CSD.")
        r = _post_onboard(cookies)
        assert r.status_code == 400
        body = r.json()
        assert body["step"] == "csd"
        assert body["manifest_signed"] is True

    conn = db()
    try:
        row = conn.execute(
            "SELECT manifest_signed_at, csd_uploaded_at, onboarding_completed_at FROM issuers WHERE id = ?",
            (issuer_id,),
        ).fetchone()
        assert row["manifest_signed_at"] is not None
        assert row["csd_uploaded_at"] is None  # not uploaded
        assert row["onboarding_completed_at"] is None
    finally:
        conn.close()
