"""Tests for 14-day trial initialization on issuer creation."""
from datetime import datetime, timedelta

import pytest

from database import db, has_column
from services.billing.subscription import can_issuer_use_sync_and_timbrado, is_issuer_trial_active
from services.issuers import create_issuer_with_token


class TestTrialInitOnCreate:
    """Verify trial_expires_at is set when creating issuers."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        yield
        # Clean up test issuers
        conn = db()
        try:
            conn.execute("DELETE FROM issuer_tokens WHERE issuer_id IN (SELECT id FROM issuers WHERE rfc = 'TEST0101010AA')")
            conn.execute("DELETE FROM issuers WHERE rfc = 'TEST0101010AA'")
            conn.commit()
        finally:
            conn.close()

    def test_should_set_trial_expires_at_on_create(self):
        """create_issuer_with_token should set trial_expires_at ~14 days from now."""
        issuer_id, _token = create_issuer_with_token("TEST0101010AA", "Trial Test SA")
        conn = db()
        try:
            if not has_column(conn, "issuers", "trial_expires_at"):
                pytest.skip("trial_expires_at column not present")
            row = conn.execute(
                "SELECT trial_expires_at FROM issuers WHERE id = ?", (issuer_id,)
            ).fetchone()
            assert row is not None
            assert row["trial_expires_at"] is not None
            expires = datetime.fromisoformat(row["trial_expires_at"])
            # Should be roughly 14 days from now (allow 1 day tolerance)
            delta = expires - datetime.now()
            assert 12 < delta.days <= 15
        finally:
            conn.close()

    def test_should_allow_emission_during_trial(self):
        """Issuer with active trial should be allowed to emit."""
        issuer_id, _ = create_issuer_with_token("TEST0101010AA", "Trial Test SA")
        assert is_issuer_trial_active(issuer_id) is True
        assert can_issuer_use_sync_and_timbrado(issuer_id, user_id=0) is True

    def test_should_block_after_trial_expired(self):
        """Issuer with expired trial and no subscription should be blocked."""
        issuer_id, _ = create_issuer_with_token("TEST0101010AA", "Trial Test SA")
        conn = db()
        try:
            if not has_column(conn, "issuers", "trial_expires_at"):
                pytest.skip("trial_expires_at column not present")
            # Force expire the trial
            conn.execute(
                "UPDATE issuers SET trial_expires_at = datetime('now', '-1 day') WHERE id = ?",
                (issuer_id,),
            )
            conn.commit()
        finally:
            conn.close()
        assert is_issuer_trial_active(issuer_id) is False
        assert can_issuer_use_sync_and_timbrado(issuer_id, user_id=0) is False
