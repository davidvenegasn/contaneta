"""Tests for services.facturapi.orgs HTTP wrappers."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_fpi_orgs_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-fpi-orgs"

# Set a key so orgs._user_key() doesn't bail before we mock requests.
os.environ.setdefault("FACTURAPI_SECRET_KEY", "sk_test_FAKE_FOR_UNIT_TESTS")

from services.facturapi import orgs as fpi_orgs  # noqa: E402


def _mock_response(status: int = 200, json_data: dict | None = None, text: str = ""):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = json_data or {}
    m.text = text or (str(json_data) if json_data else "")
    return m


def test_create_organization_returns_id_on_success():
    with patch("services.facturapi.orgs.requests.post") as p:
        p.return_value = _mock_response(200, {"id": "org_abc123", "name": "Test"})
        result = fpi_orgs.create_organization(legal_name="Mi Empresa SA de CV")
        assert result["id"] == "org_abc123"
        args, kwargs = p.call_args
        assert args[0].endswith("/organizations")
        assert kwargs["json"]["name"] == "Mi Empresa SA de CV"
        assert kwargs["headers"]["Authorization"].startswith("Bearer ")


def test_create_organization_raises_on_4xx():
    with patch("services.facturapi.orgs.requests.post") as p:
        p.return_value = _mock_response(401, text="Unauthorized")
        with pytest.raises(fpi_orgs.FacturapiOrgsError) as exc_info:
            fpi_orgs.create_organization(legal_name="X")
        assert exc_info.value.status == 401


def test_create_organization_requires_legal_name():
    with pytest.raises(fpi_orgs.FacturapiOrgsError):
        fpi_orgs.create_organization(legal_name="")


def test_upload_csd_sends_multipart():
    with patch("services.facturapi.orgs.requests.put") as p:
        p.return_value = _mock_response(200, {"id": "org_abc", "is_production_ready": True})
        result = fpi_orgs.upload_csd(
            "org_abc",
            cer_bytes=b"x" * 200,
            key_bytes=b"y" * 200,
            password="hunter2",
        )
        assert result["id"] == "org_abc"
        _, kwargs = p.call_args
        assert "files" in kwargs
        assert kwargs["data"]["password"] == "hunter2"


def test_upload_csd_validates_inputs():
    with pytest.raises(fpi_orgs.FacturapiOrgsError):
        fpi_orgs.upload_csd("", cer_bytes=b"x", key_bytes=b"y", password="p")
    with pytest.raises(fpi_orgs.FacturapiOrgsError):
        fpi_orgs.upload_csd("org_abc", cer_bytes=b"", key_bytes=b"y", password="p")
    with pytest.raises(fpi_orgs.FacturapiOrgsError):
        fpi_orgs.upload_csd("org_abc", cer_bytes=b"x", key_bytes=b"y", password="")


def test_update_legal_info_no_op_when_no_fields():
    # No HTTP call if nothing to update.
    with patch("services.facturapi.orgs.requests.put") as p:
        result = fpi_orgs.update_legal_info("org_abc")
        assert result == {}
        p.assert_not_called()


def test_user_key_raises_when_env_unset(monkeypatch):
    monkeypatch.delenv("FACTURAPI_SECRET_KEY", raising=False)
    with pytest.raises(fpi_orgs.FacturapiOrgsError):
        fpi_orgs._user_key()


def test_sign_manifesto_hits_fiel_endpoint():
    """sign_manifesto must PUT to /organizations/{id}/fiel with multipart FIEL bytes."""
    with patch("services.facturapi.orgs.requests.put") as p:
        p.return_value = _mock_response(200, {"id": "org_xyz", "legal": {"tax_id": "VEND980918UR1"}})
        result = fpi_orgs.sign_manifesto(
            "org_xyz",
            cer_bytes=b"x" * 200,
            key_bytes=b"y" * 200,
            password="hunter2",
        )
        assert result["id"] == "org_xyz"
        args, kwargs = p.call_args
        assert args[0].endswith("/organizations/org_xyz/fiel")
        assert "files" in kwargs
        assert kwargs["data"]["password"] == "hunter2"


def test_sign_manifesto_raises_on_bad_password():
    with patch("services.facturapi.orgs.requests.put") as p:
        p.return_value = _mock_response(400, text='{"message":"La contraseña es incorrecta"}')
        with pytest.raises(fpi_orgs.FacturapiOrgsError) as exc_info:
            fpi_orgs.sign_manifesto(
                "org_xyz", cer_bytes=b"x" * 200, key_bytes=b"y" * 200, password="wrong",
            )
        assert exc_info.value.status == 400


def test_sign_manifesto_validates_inputs():
    with pytest.raises(fpi_orgs.FacturapiOrgsError):
        fpi_orgs.sign_manifesto("", cer_bytes=b"x", key_bytes=b"y", password="p")
    with pytest.raises(fpi_orgs.FacturapiOrgsError):
        fpi_orgs.sign_manifesto("org_xyz", cer_bytes=b"", key_bytes=b"y", password="p")
    with pytest.raises(fpi_orgs.FacturapiOrgsError):
        fpi_orgs.sign_manifesto("org_xyz", cer_bytes=b"x", key_bytes=b"y", password="")


def test_get_org_api_key_test_mode():
    """get_org_api_key should GET /apikeys/test and return the value."""
    with patch("services.facturapi.orgs.requests.get") as p:
        p.return_value = _mock_response(200, {"value": "sk_test_org_key_123"})
        key = fpi_orgs.get_org_api_key("org_abc", mode="test")
        assert key == "sk_test_org_key_123"
        args, _ = p.call_args
        assert args[0].endswith("/organizations/org_abc/apikeys/test")


def test_get_org_api_key_live_mode_returns_first_from_list():
    """Live mode returns a list; should extract first item's value."""
    with patch("services.facturapi.orgs.requests.get") as p:
        p.return_value = _mock_response(200, json_data=None)
        p.return_value.json.return_value = [{"value": "sk_live_key_1"}, {"value": "sk_live_key_2"}]
        key = fpi_orgs.get_org_api_key("org_abc", mode="live")
        assert key == "sk_live_key_1"


def test_get_org_api_key_raises_on_404():
    """Should raise FacturapiOrgsError on 404."""
    with patch("services.facturapi.orgs.requests.get") as p:
        p.return_value = _mock_response(404, text="Not Found")
        with pytest.raises(fpi_orgs.FacturapiOrgsError) as exc_info:
            fpi_orgs.get_org_api_key("org_missing", mode="test")
        assert exc_info.value.status == 404


def test_get_org_api_key_invalid_mode():
    """Invalid mode should raise immediately."""
    with pytest.raises(fpi_orgs.FacturapiOrgsError):
        fpi_orgs.get_org_api_key("org_abc", mode="invalid")
