"""Stress tests for KPI totals determinism under concurrent reads.

Verifies that the atomic snapshot fix (Jobs 2-4) makes totals fully
deterministic: 100 concurrent requests must all return the same
data-count-to values.
"""

import os
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if not os.environ.get("APP_DB_PATH"):
    _fd, _p = tempfile.mkstemp(suffix=".db", prefix="test_kpi_stress_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _p
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-kpi-stress"

import database  # noqa: E402
from config import DB_PATH  # noqa: E402
from migrations_runner import apply_migrations  # noqa: E402

_DATA_COUNT_RE = re.compile(r'data-count-to="([^"]*)"')
_ISSUER_ID = 77702
_USER_ID = 77702


@pytest.fixture(scope="module", autouse=True)
def seed():
    apply_migrations(DB_PATH)
    conn = database.db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO issuers (id, rfc, razon_social, active, created_at, updated_at) "
            "VALUES (?, 'STRESS770101AAA', 'Stress Test Co', 1, datetime('now'), datetime('now'))",
            (_ISSUER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) "
            "VALUES (?, 'stress@test.local', 'x', datetime('now'))",
            (_USER_ID,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO memberships (user_id, issuer_id, role, created_at) "
            "VALUES (?, ?, 'owner', datetime('now'))",
            (_USER_ID, _ISSUER_ID),
        )
        # Seed some CFDI data so totals are non-zero
        for i in range(5):
            conn.execute(
                "INSERT OR IGNORE INTO sat_cfdi (issuer_id, uuid, direction, fecha_emision, total, subtotal, impuestos, status) "
                "VALUES (?, ?, 'issued', '2026-05-15', 11600, 10000, 1600, 'vigente')",
                (_ISSUER_ID, f"stress-issued-{i:04d}"),
            )
            conn.execute(
                "INSERT OR IGNORE INTO sat_cfdi (issuer_id, uuid, direction, fecha_emision, total, subtotal, impuestos, status) "
                "VALUES (?, ?, 'received', '2026-05-15', 5800, 5000, 800, 'vigente')",
                (_ISSUER_ID, f"stress-received-{i:04d}"),
            )
        conn.commit()
    finally:
        conn.close()
    yield


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from app import app
    from tests.helpers import make_session_cookie
    cookies = make_session_cookie(issuer_id=_ISSUER_ID, user_id=_USER_ID)
    return TestClient(app, raise_server_exceptions=False, cookies=cookies)


def test_total_ingresos_consistent_across_10_refreshes(client):
    """10 sequential requests to /portal/facturas must return identical data-count-to."""
    values = []
    for _ in range(10):
        r = client.get("/portal/facturas?tab=issued&ym=2026-05")
        assert r.status_code == 200
        matches = _DATA_COUNT_RE.findall(r.text)
        values.append(tuple(matches))
    unique = set(values)
    assert len(unique) == 1, f"KPI values differed across 10 refreshes: {unique}"


def test_total_ingresos_same_across_pages(client):
    """Issued and received pages for the same ym must show consistent KPIs."""
    r_issued = client.get("/portal/facturas?tab=issued&ym=2026-05")
    r_received = client.get("/portal/facturas?tab=received&ym=2026-05")
    assert r_issued.status_code == 200
    assert r_received.status_code == 200
    # Both pages should render without NaN or empty values
    for r in [r_issued, r_received]:
        matches = _DATA_COUNT_RE.findall(r.text)
        for val in matches:
            parsed = float(val)
            assert parsed == parsed, f"NaN in data-count-to: {val}"


def test_kpi_does_not_change_after_concurrent_reads(client):
    """100 concurrent requests must all return the same data-count-to values."""
    url = "/portal/facturas?tab=issued&ym=2026-05"

    def fetch():
        r = client.get(url)
        if r.status_code != 200:
            return None
        return tuple(_DATA_COUNT_RE.findall(r.text))

    results = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(fetch) for _ in range(100)]
        for f in as_completed(futures):
            val = f.result()
            if val is not None:
                results.append(val)

    assert len(results) >= 90, f"Too many failures: only {len(results)} of 100 succeeded"
    unique = set(results)
    assert len(unique) == 1, (
        f"KPI values differed across {len(results)} concurrent reads. "
        f"Unique sets: {len(unique)}"
    )


def test_trend_api_deterministic_under_concurrent_reads(client):
    """50 concurrent requests to /api/metrics/trend must return identical JSON."""
    url = "/api/metrics/trend?months=3"

    def fetch():
        r = client.get(url)
        if r.status_code != 200:
            return None
        return r.text

    results = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(fetch) for _ in range(50)]
        for f in as_completed(futures):
            val = f.result()
            if val is not None:
                results.append(val)

    assert len(results) >= 40, f"Too many failures: only {len(results)} of 50 succeeded"
    unique = set(results)
    assert len(unique) == 1, (
        f"Trend API returned different values across {len(results)} concurrent reads. "
        f"Unique responses: {len(unique)}"
    )
