"""Tests for FIEL certificate expiry calculation and plan usage."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from database import db


class TestFielExpiryCalc:
    """Verify extract_fiel_subject returns expiry info."""

    def test_should_return_days_until_expiry(self):
        """Mock the cert parsing to verify expiry calculation."""
        from services.sat import sat_credentials_secure as scs

        mock_cert = MagicMock()
        future_date = datetime(2028, 6, 15, tzinfo=timezone.utc)
        mock_cert.not_valid_after_utc = future_date
        mock_cert.subject = []

        with patch.object(scs, "ensure_fiel_encrypted"), \
             patch.object(scs, "_read_sat_credentials_row", return_value={"fiel_cer_path": "fake.cer"}), \
             patch.object(scs, "_abs_under_base", return_value="/tmp/fake.cer"), \
             patch("builtins.open", MagicMock(return_value=MagicMock(
                 __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=b"fake"))),
                 __exit__=MagicMock(return_value=False),
             ))), \
             patch.object(scs, "decrypt_bytes", return_value=b"fake_cer_bytes"), \
             patch("cryptography.x509.load_der_x509_certificate", return_value=mock_cert):
            result = scs.extract_fiel_subject(1)
            assert "expires_at" in result
            assert "days_until_expiry" in result
            assert result["days_until_expiry"] > 0
            assert "2028-06-15" in result["expires_at"]

    def test_should_return_negative_days_for_expired_cert(self):
        """Expired cert should return negative days_until_expiry."""
        from services.sat import sat_credentials_secure as scs

        mock_cert = MagicMock()
        past_date = datetime(2020, 1, 1, tzinfo=timezone.utc)
        mock_cert.not_valid_after_utc = past_date
        mock_cert.subject = []

        with patch.object(scs, "ensure_fiel_encrypted"), \
             patch.object(scs, "_read_sat_credentials_row", return_value={"fiel_cer_path": "fake.cer"}), \
             patch.object(scs, "_abs_under_base", return_value="/tmp/fake.cer"), \
             patch("builtins.open", MagicMock(return_value=MagicMock(
                 __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=b"fake"))),
                 __exit__=MagicMock(return_value=False),
             ))), \
             patch.object(scs, "decrypt_bytes", return_value=b"fake_cer_bytes"), \
             patch("cryptography.x509.load_der_x509_certificate", return_value=mock_cert):
            result = scs.extract_fiel_subject(1)
            assert result["days_until_expiry"] < 0


class TestPlanUsageBadge:
    """Verify plan usage data is accessible for badge rendering."""

    @pytest.fixture(autouse=True)
    def setup_issuer(self):
        conn = db()
        try:
            conn.execute(
                "INSERT INTO issuers (rfc, razon_social, active, created_at, updated_at) VALUES (?, ?, 1, datetime('now'), datetime('now'))",
                ("PLAN0101010AA", "Plan Test SA"),
            )
            conn.commit()
            self.issuer_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        finally:
            conn.close()
        yield
        conn = db()
        try:
            conn.execute("DELETE FROM plan_usage WHERE issuer_id = ?", (self.issuer_id,))
            conn.execute("DELETE FROM issuers WHERE id = ?", (self.issuer_id,))
            conn.commit()
        finally:
            conn.close()

    def test_should_return_count_and_limit(self):
        from services.billing.plans import check_limit
        result = check_limit(issuer_id=self.issuer_id, action="invoice")
        assert "usage" in result
        assert "limit" in result
        assert "allowed" in result
        assert "plan" in result
        assert isinstance(result["usage"], int)
        assert isinstance(result["limit"], int)

    def test_should_block_when_limit_reached(self):
        from services.billing.plans import check_limit, increment_usage, get_plan_config, get_issuer_plan
        plan = get_issuer_plan(self.issuer_id)
        config = get_plan_config(plan)
        limit = config["invoices_per_month"]
        # Fill up to the limit
        for _ in range(limit):
            increment_usage(self.issuer_id, "invoices_count")
        result = check_limit(self.issuer_id, "invoice")
        assert result["allowed"] is False
        assert "Limite" in result["reason"]
