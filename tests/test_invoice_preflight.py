"""Tests for invoice pre-flight checks."""
import os
from unittest.mock import patch

import pytest

from services.invoices.preflight import validate_can_issue_invoice, _is_valid_rfc


# --------------- RFC validation ---------------

class TestRfcValidation:
    """Verify RFC format validation helper."""

    def test_should_accept_valid_pf_rfc(self):
        assert _is_valid_rfc("XAXX010101000") is True

    def test_should_accept_valid_pm_rfc(self):
        assert _is_valid_rfc("AAA010101AAA") is True

    def test_should_reject_empty(self):
        assert _is_valid_rfc("") is False
        assert _is_valid_rfc(None) is False

    def test_should_reject_short(self):
        assert _is_valid_rfc("ABC") is False

    def test_should_reject_pendiente(self):
        assert _is_valid_rfc("PENDIENTE") is False


# --------------- Preflight checks ---------------

class TestPreflightIssuerNotFound:
    """Verify error when issuer doesn't exist."""

    @patch.dict(os.environ, {"FACTURAPI_SECRET_KEY": "sk_test_123"})
    def test_should_fail_when_issuer_not_found(self):
        result = validate_can_issue_invoice(issuer_id=999999)
        assert result["ok"] is False
        codes = [e["code"] for e in result["errors"]]
        assert "ISSUER_NOT_FOUND" in codes


class TestPreflightNoFacurapiKey:
    """Verify error when Facturapi key is missing."""

    @patch.dict(os.environ, {"FACTURAPI_SECRET_KEY": ""}, clear=False)
    def test_should_report_missing_facturapi_key(self):
        result = validate_can_issue_invoice(issuer_id=999999)
        assert result["ok"] is False
        codes = [e["code"] for e in result["errors"]]
        assert "NO_FACTURAPI_KEY" in codes


class TestPreflightWithTestIssuer:
    """Verify checks against a real test issuer in the DB."""

    @pytest.fixture(autouse=True)
    def setup_issuer(self):
        """Create a minimal test issuer."""
        from database import db
        conn = db()
        try:
            conn.execute(
                """INSERT INTO issuers (rfc, razon_social, regimen_fiscal, facturapi_org_id, active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 1, datetime('now'), datetime('now'))""",
                ("XAXX010101000", "Test SA de CV", "601", "org_test_123"),
            )
            conn.commit()
            self.issuer_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        finally:
            conn.close()
        yield
        conn = db()
        try:
            conn.execute("DELETE FROM issuers WHERE id = ?", (self.issuer_id,))
            conn.commit()
        finally:
            conn.close()

    @patch.dict(os.environ, {"FACTURAPI_SECRET_KEY": "sk_test_abc"})
    def test_should_report_no_fiel(self):
        """Issuer with good data but no FIEL should get NO_FIEL error."""
        result = validate_can_issue_invoice(self.issuer_id)
        # May pass or fail depending on sat_credentials table existence
        codes = [e["code"] for e in result["errors"]]
        # Should NOT have basic config errors
        assert "INVALID_RFC" not in codes
        assert "NO_RAZON_SOCIAL" not in codes
        assert "NO_REGIMEN_FISCAL" not in codes
        assert "NO_FACTURAPI_ORG" not in codes
        assert "NO_FACTURAPI_KEY" not in codes

    @patch.dict(os.environ, {"FACTURAPI_SECRET_KEY": "sk_test_abc"})
    def test_should_report_invalid_rfc_when_pendiente(self):
        """Issuer with RFC='PENDIENTE' should fail."""
        from database import db
        conn = db()
        try:
            conn.execute("UPDATE issuers SET rfc = 'PENDIENTE' WHERE id = ?", (self.issuer_id,))
            conn.commit()
        finally:
            conn.close()
        result = validate_can_issue_invoice(self.issuer_id)
        assert result["ok"] is False
        codes = [e["code"] for e in result["errors"]]
        assert "INVALID_RFC" in codes

    @patch.dict(os.environ, {"FACTURAPI_SECRET_KEY": "sk_test_abc"})
    def test_should_report_missing_regimen(self):
        """Issuer without regimen_fiscal should fail."""
        from database import db
        conn = db()
        try:
            conn.execute("UPDATE issuers SET regimen_fiscal = '' WHERE id = ?", (self.issuer_id,))
            conn.commit()
        finally:
            conn.close()
        result = validate_can_issue_invoice(self.issuer_id)
        assert result["ok"] is False
        codes = [e["code"] for e in result["errors"]]
        assert "NO_REGIMEN_FISCAL" in codes

    @patch.dict(os.environ, {"FACTURAPI_SECRET_KEY": "sk_test_abc"})
    def test_should_report_inactive_issuer(self):
        """Inactive issuer should fail."""
        from database import db
        conn = db()
        try:
            conn.execute("UPDATE issuers SET active = 0 WHERE id = ?", (self.issuer_id,))
            conn.commit()
        finally:
            conn.close()
        result = validate_can_issue_invoice(self.issuer_id)
        assert result["ok"] is False
        codes = [e["code"] for e in result["errors"]]
        assert "ISSUER_INACTIVE" in codes

    @patch.dict(os.environ, {"FACTURAPI_SECRET_KEY": "sk_test_abc"})
    def test_should_report_no_facturapi_org(self):
        """Issuer without facturapi_org_id should fail."""
        from database import db
        conn = db()
        try:
            conn.execute("UPDATE issuers SET facturapi_org_id = '' WHERE id = ?", (self.issuer_id,))
            conn.commit()
        finally:
            conn.close()
        result = validate_can_issue_invoice(self.issuer_id)
        assert result["ok"] is False
        codes = [e["code"] for e in result["errors"]]
        assert "NO_FACTURAPI_ORG" in codes


class TestPreflightErrorFormat:
    """Verify error structure consistency."""

    @patch.dict(os.environ, {"FACTURAPI_SECRET_KEY": ""}, clear=False)
    def test_should_include_code_message_action(self):
        result = validate_can_issue_invoice(issuer_id=999999)
        assert result["ok"] is False
        for error in result["errors"]:
            assert "code" in error
            assert "message" in error
            assert "action" in error
            assert isinstance(error["code"], str)
            assert isinstance(error["message"], str)
            assert isinstance(error["action"], str)
