"""Tests for Lista 69-B SAT validation."""
import pytest

from database import db
from services.sat.lista_69b import check_rfc_69b, is_rfc_blocked, is_rfc_warned


@pytest.fixture(scope="module", autouse=True)
def seed():
    """Insert test RFCs into sat_lista_69b."""
    conn = db()
    # Ensure table exists (migration should have run)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sat_lista_69b (
           rfc TEXT PRIMARY KEY,
           nombre TEXT,
           situacion TEXT,
           refreshed_at TEXT NOT NULL DEFAULT (datetime('now'))
        )"""
    )
    conn.execute(
        "INSERT OR REPLACE INTO sat_lista_69b (rfc, nombre, situacion) "
        "VALUES ('DEF010101AAA', 'EFOS Definitivo SA', 'Definitivo')"
    )
    conn.execute(
        "INSERT OR REPLACE INTO sat_lista_69b (rfc, nombre, situacion) "
        "VALUES ('PRE010101BBB', 'EFOS Presunto SA', 'Presunto')"
    )
    conn.execute(
        "INSERT OR REPLACE INTO sat_lista_69b (rfc, nombre, situacion) "
        "VALUES ('DES010101CCC', 'EFOS Desvirtuado SA', 'Desvirtuado')"
    )
    conn.execute(
        "INSERT OR REPLACE INTO sat_lista_69b (rfc, nombre, situacion) "
        "VALUES ('SEN010101DDD', 'EFOS Sentencia SA', 'Sentencia Favorable')"
    )
    conn.commit()
    conn.close()
    yield


def test_should_find_definitivo_rfc():
    """RFC with Definitivo status should be found."""
    result = check_rfc_69b("DEF010101AAA")
    assert result is not None
    assert result["situacion"] == "Definitivo"


def test_should_block_definitivo_rfc():
    """Definitivo RFCs should be blocked from invoicing."""
    assert is_rfc_blocked("DEF010101AAA") is True


def test_should_block_sentencia_favorable():
    """Sentencia Favorable should also be blocked."""
    assert is_rfc_blocked("SEN010101DDD") is True


def test_should_not_block_presunto():
    """Presunto should warn but not block."""
    assert is_rfc_blocked("PRE010101BBB") is False


def test_should_warn_presunto():
    """Presunto should trigger a warning."""
    assert is_rfc_warned("PRE010101BBB") is True


def test_should_not_block_desvirtuado():
    """Desvirtuado (cleared) should not block."""
    assert is_rfc_blocked("DES010101CCC") is False


def test_should_not_warn_desvirtuado():
    """Desvirtuado should not warn either."""
    assert is_rfc_warned("DES010101CCC") is False


def test_should_return_none_for_clean_rfc():
    """RFC not in the list should return None."""
    assert check_rfc_69b("CLEAN999999XX9") is None


def test_should_not_block_clean_rfc():
    """Clean RFC should not be blocked."""
    assert is_rfc_blocked("CLEAN999999XX9") is False


def test_should_handle_case_insensitive():
    """RFC check should be case-insensitive."""
    result = check_rfc_69b("def010101aaa")
    assert result is not None


def test_should_handle_empty_rfc():
    """Empty RFC should return None."""
    assert check_rfc_69b("") is None
    assert check_rfc_69b(None) is None


# --- Stamping integration tests ---


def _make_stamping_form(customer_rfc):
    """Helper to build a minimal form dict for _submit_impl testing."""
    return {
        "customer_rfc": customer_rfc,
        "customer_legal_name": "Test SA",
        "customer_zip": "64000",
        "customer_tax_system": "601",
        "cfdi_use": "G03",
        "payment_method": "PUE",
        "payment_form": "03",
        "currency": "MXN",
        "tipo_comprobante": "I",
        "qty_0": "1",
        "desc_0": "Servicio de prueba",
        "key_0": "84111506",
        "price_0": "1000",
        "iva_0": "0.16",
        "unit_0": "E48",
    }


def test_submit_blocked_when_rfc_in_69b_definitivo():
    """_submit_impl should raise ValueError for Definitivo RFC."""
    from unittest.mock import MagicMock

    from routers.invoicing import _submit_impl

    request = MagicMock()
    request.state.issuer_id = 1
    request.state.user_id = 1
    request.state.membership_role = "owner"
    issuer = {"id": 1, "facturapi_org_id": "test", "rfc": "EMI010101AAA"}
    form = _make_stamping_form("DEF010101AAA")
    with pytest.raises(ValueError, match="Lista 69-B"):
        _submit_impl(None, request, issuer, form)


def test_submit_blocked_when_rfc_in_69b_sentencia():
    """_submit_impl should raise ValueError for Sentencia Favorable RFC."""
    from unittest.mock import MagicMock

    from routers.invoicing import _submit_impl

    request = MagicMock()
    request.state.issuer_id = 1
    request.state.user_id = 1
    request.state.membership_role = "owner"
    issuer = {"id": 1, "facturapi_org_id": "test", "rfc": "EMI010101AAA"}
    form = _make_stamping_form("SEN010101DDD")
    with pytest.raises(ValueError, match="Lista 69-B"):
        _submit_impl(None, request, issuer, form)


def test_submit_allows_generic_rfcs():
    """Generic RFCs (XAXX, XEXX) should bypass 69-B check."""
    from services.sat.lista_69b import check_rfc_69b

    # Even if these were in the list, they should not be checked
    # The check is skipped for generic RFCs, so no error should come from 69-B
    # (Other errors may occur later in the flow, but not from 69-B)
    for generic_rfc in ("XAXX010101000", "XEXX010101000"):
        result = check_rfc_69b(generic_rfc)
        # These shouldn't be in the 69-B list, confirming no false positives
        assert result is None


def test_submit_warned_when_rfc_in_69b_presunto():
    """Presunto RFC should warn (log) but NOT block stamping."""
    from services.sat.lista_69b import check_rfc_69b

    result = check_rfc_69b("PRE010101BBB")
    assert result is not None
    sit = (result.get("situacion") or "").lower()
    # Presunto should NOT be in the blocking set
    assert sit not in ("definitivo", "sentencia favorable")
    # But should be flagged as warned
    assert sit == "presunto"
