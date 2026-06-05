"""Tests for the facturapi_provision_org job handler + signup integration."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_fpi_provision_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-fpi-provision"
os.environ.setdefault("FACTURAPI_SECRET_KEY", "sk_test_FAKE_FOR_UNIT_TESTS")

from database import db
from services import issuers as issuers_service
from services.facturapi import provision as fpi_provision
from services.facturapi.orgs import FacturapiOrgsError


def _make_issuer(rfc: str, razon_social: str) -> int:
    issuer_id, _ = issuers_service.create_issuer_with_token(
        rfc=rfc,
        razon_social=razon_social,
        regimen_fiscal="616",
    )
    return issuer_id


def test_should_skip_when_issuer_already_provisioned():
    issuer_id = _make_issuer("AAA010101AAA", "Already Provisioned SA")
    conn = db()
    try:
        conn.execute(
            "UPDATE issuers SET facturapi_org_id = 'org_existing' WHERE id = ?",
            (issuer_id,),
        )
        conn.commit()
    finally:
        conn.close()

    with patch("services.facturapi.provision.fpi_orgs.create_organization") as mock_create:
        result = fpi_provision.handle_facturapi_provision_org(
            {"issuer_id": issuer_id, "name": "facturapi_provision_org"}, None
        )
        assert result["skipped"] is True
        assert result["reason"] == "already provisioned"
        mock_create.assert_not_called()


def test_should_persist_org_id_on_success():
    issuer_id = _make_issuer("BBB010101BBB", "New Tenant SA")
    with patch("services.facturapi.provision.fpi_orgs.create_organization") as mock_create:
        mock_create.return_value = {"id": "org_new_42", "name": "New Tenant SA"}
        result = fpi_provision.handle_facturapi_provision_org(
            {"issuer_id": issuer_id, "name": "facturapi_provision_org"}, None
        )
        assert result["org_id"] == "org_new_42"

    conn = db()
    try:
        row = conn.execute(
            "SELECT facturapi_org_id, facturapi_provisioned_at FROM issuers WHERE id = ?",
            (issuer_id,),
        ).fetchone()
        assert row["facturapi_org_id"] == "org_new_42"
        assert row["facturapi_provisioned_at"] is not None
    finally:
        conn.close()


def test_should_raise_on_facturapi_error_so_worker_retries():
    issuer_id = _make_issuer("CCC010101CCC", "Will Retry SA")
    with patch("services.facturapi.provision.fpi_orgs.create_organization") as mock_create:
        mock_create.side_effect = FacturapiOrgsError(503, "Service Unavailable")
        try:
            fpi_provision.handle_facturapi_provision_org(
                {"issuer_id": issuer_id, "name": "facturapi_provision_org"}, None
            )
        except FacturapiOrgsError as e:
            assert e.status == 503
        else:
            assert False, "Expected FacturapiOrgsError to be re-raised"


def test_should_skip_when_issuer_missing():
    result = fpi_provision.handle_facturapi_provision_org(
        {"issuer_id": 999999, "name": "facturapi_provision_org"}, None
    )
    assert result["skipped"] is True
    assert result["reason"] == "issuer not found"


def test_should_use_fallback_legal_name_when_razon_social_empty():
    """Even if razon_social is blank, provisioning must still produce a valid POST body."""
    issuer_id, _ = issuers_service.create_issuer_with_token(
        rfc="DDD010101DDD", razon_social="", regimen_fiscal="616"
    )
    with patch("services.facturapi.provision.fpi_orgs.create_organization") as mock_create:
        mock_create.return_value = {"id": "org_fallback"}
        fpi_provision.handle_facturapi_provision_org(
            {"issuer_id": issuer_id, "name": "facturapi_provision_org"}, None
        )
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["legal_name"].startswith("Tenant ")


def test_create_issuer_with_token_enqueues_provision_job():
    """The signup path must enqueue a facturapi_provision_org job."""
    # Drain any existing rows so we can assert presence below.
    conn = db()
    try:
        conn.execute("DELETE FROM jobs WHERE name = 'facturapi_provision_org' AND issuer_id = 0")
        conn.commit()
    finally:
        conn.close()

    issuer_id = _make_issuer("EEE010101EEE", "Signup Enqueue SA")

    conn = db()
    try:
        row = conn.execute(
            "SELECT name, status FROM jobs WHERE name = 'facturapi_provision_org' AND issuer_id = ? ORDER BY id DESC LIMIT 1",
            (issuer_id,),
        ).fetchone()
        assert row is not None, "expected a queued facturapi_provision_org job"
        assert row["status"] in ("queued", "running")
    finally:
        conn.close()
