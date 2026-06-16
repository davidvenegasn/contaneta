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
