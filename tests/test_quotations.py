"""
Tests for the quotations module: create, list, get, update-status, delete, update-items,
filter by status, and cross-tenant isolation.

Uses real SQLite test fixtures (not mocks).
"""
import os
import sys
import sqlite3
import tempfile
from pathlib import Path

import pytest

# Fix DB path before importing app/config
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_quotations_")
os.close(_fd)
os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-quotations"


def _bootstrap_schema():
    """Create the minimal schema needed for quotation tests directly via SQL.

    This avoids depending on apply_migrations() which may fail on
    migrations that use unsupported syntax in some environments.
    """
    conn = sqlite3.connect(_test_db, timeout=30)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS issuers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rfc TEXT,
            razon_social TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            active INTEGER NOT NULL DEFAULT 1,
            regimen_fiscal TEXT,
            facturapi_org_id TEXT,
            trial_expires_at TEXT
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            phone TEXT,
            password_hash TEXT,
            oauth_provider TEXT,
            oauth_id TEXT,
            name TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            password_changed_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS memberships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            issuer_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('viewer', 'accountant', 'owner', 'admin', 'staff')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(user_id, issuer_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS quotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issuer_id INTEGER NOT NULL,
            customer_rfc TEXT NOT NULL,
            customer_legal_name TEXT NOT NULL,
            customer_email TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            public_token TEXT UNIQUE NOT NULL,
            valid_until TEXT,
            notes TEXT,
            responded_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            folio TEXT,
            iva_rate REAL,
            sent_at TEXT,
            accepted_at TEXT,
            rejected_at TEXT,
            decision_ip TEXT,
            decision_user_agent TEXT,
            rejection_reason TEXT,
            currency TEXT,
            metadata_json TEXT,
            FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_quotations_issuer_id ON quotations(issuer_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_quotations_public_token ON quotations(public_token);

        CREATE TABLE IF NOT EXISTS quotation_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quotation_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            quantity REAL NOT NULL DEFAULT 1,
            unit_price REAL NOT NULL DEFAULT 0,
            iva_rate REAL NOT NULL DEFAULT 0.16,
            product_id INTEGER,
            sort_order INTEGER NOT NULL DEFAULT 0,
            extra_desc TEXT,
            FOREIGN KEY (quotation_id) REFERENCES quotations(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_quotation_items_quotation_id ON quotation_items(quotation_id);

        CREATE TABLE IF NOT EXISTS issuer_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issuer_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            unit_price REAL NOT NULL DEFAULT 0,
            iva_rate REAL NOT NULL DEFAULT 0.16,
            product_key TEXT,
            unit_key TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (issuer_id) REFERENCES issuers(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS rate_limit_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL,
            ip TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_rate_limit_key_ip ON rate_limit_entries(key, ip);
    """)
    conn.commit()
    conn.close()


_bootstrap_schema()

from fastapi.testclient import TestClient  # noqa: E402

from database import db  # noqa: E402
from services.auth.csrf import generate_csrf_token  # noqa: E402
from tests.helpers import make_session_cookie  # noqa: E402

from app import app  # noqa: E402


ISSUER_A = 20001
ISSUER_B = 20002
USER_A = 20001
USER_B = 20002


def _seed():
    """Create two tenants (issuers + users + memberships) for testing."""
    conn = db()
    try:
        # Clean up any prior test data at these IDs
        conn.execute(
            "DELETE FROM quotation_items WHERE quotation_id IN "
            "(SELECT id FROM quotations WHERE issuer_id IN (?, ?))",
            (ISSUER_A, ISSUER_B),
        )
        conn.execute("DELETE FROM quotations WHERE issuer_id IN (?, ?)", (ISSUER_A, ISSUER_B))
        conn.execute(
            "DELETE FROM memberships WHERE user_id IN (?, ?) OR issuer_id IN (?, ?)",
            (USER_A, USER_B, ISSUER_A, ISSUER_B),
        )
        conn.execute("DELETE FROM users WHERE id IN (?, ?)", (USER_A, USER_B))
        conn.execute("DELETE FROM issuers WHERE id IN (?, ?)", (ISSUER_A, ISSUER_B))

        conn.execute(
            "INSERT INTO issuers (id, rfc, razon_social, regimen_fiscal, active, created_at, updated_at) "
            "VALUES (?, 'TSTA200010XX', 'Test Issuer A', '601', 1, datetime('now'), datetime('now'))",
            (ISSUER_A,),
        )
        conn.execute(
            "INSERT INTO issuers (id, rfc, razon_social, regimen_fiscal, active, created_at, updated_at) "
            "VALUES (?, 'TSTB200020XX', 'Test Issuer B', '612', 1, datetime('now'), datetime('now'))",
            (ISSUER_B,),
        )
        conn.execute(
            "INSERT INTO users (id, email, password_hash, created_at) "
            "VALUES (?, 'quota@test.local', '$2b$12$x', datetime('now'))",
            (USER_A,),
        )
        conn.execute(
            "INSERT INTO users (id, email, password_hash, created_at) "
            "VALUES (?, 'quotb@test.local', '$2b$12$x', datetime('now'))",
            (USER_B,),
        )
        conn.execute(
            "INSERT INTO memberships (user_id, issuer_id, role, created_at) "
            "VALUES (?, ?, 'owner', datetime('now'))",
            (USER_A, ISSUER_A),
        )
        conn.execute(
            "INSERT INTO memberships (user_id, issuer_id, role, created_at) "
            "VALUES (?, ?, 'owner', datetime('now'))",
            (USER_B, ISSUER_B),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="module")
def client():
    _seed()
    return TestClient(app)


@pytest.fixture(scope="module")
def cookies_a():
    return make_session_cookie(issuer_id=ISSUER_A, user_id=USER_A)


@pytest.fixture(scope="module")
def cookies_b():
    return make_session_cookie(issuer_id=ISSUER_B, user_id=USER_B)


def _csrf_headers():
    """Return a dict with a valid CSRF token header."""
    return {"X-CSRF-Token": generate_csrf_token()}


def _insert_quotation(issuer_id, customer_legal_name="Test Client", customer_rfc="XAXX010101000",
                       status="draft", items=None):
    """Insert a quotation directly via SQL to avoid rate limiting.

    Returns the quotation id.
    """
    import secrets
    conn = db()
    try:
        conn.execute(
            "INSERT INTO quotations (issuer_id, folio, customer_rfc, customer_legal_name, "
            "status, public_token, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (issuer_id, f"Q-TEST-{secrets.token_hex(4)}", customer_rfc, customer_legal_name,
             status, secrets.token_urlsafe(16)),
        )
        qid = conn.execute("SELECT last_insert_rowid() AS rid").fetchone()["rid"]
        for idx, it in enumerate(items or [{"description": "Test item", "quantity": 1, "unit_price": 100, "iva_rate": 0.16}]):
            conn.execute(
                "INSERT INTO quotation_items (quotation_id, description, quantity, unit_price, iva_rate, sort_order) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (qid, it.get("description", "Item"), float(it.get("quantity", 1)),
                 float(it.get("unit_price", 100)), float(it.get("iva_rate", 0.16)), idx),
            )
        conn.commit()
        return qid
    finally:
        conn.close()


# ---- Create quotation ----

def test_should_create_quotation_successfully(client, cookies_a):
    payload = {
        "customer_rfc": "XAXX010101000",
        "customer_legal_name": "Cliente Test A",
        "customer_email": "test@example.com",
        "status": "draft",
        "items": [
            {"description": "Servicio de consultoría", "quantity": 2, "unit_price": 1000, "iva_rate": 0.16},
            {"description": "Licencia de software", "quantity": 1, "unit_price": 5000, "iva_rate": 0.16},
        ],
    }
    r = client.post("/api/quotations/create", json=payload, cookies=cookies_a, headers=_csrf_headers())
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    assert "data" in j
    assert "id" in j["data"]
    assert "public_token" in j["data"]


def test_should_fail_create_without_items(client, cookies_a):
    payload = {
        "customer_rfc": "XAXX010101000",
        "customer_legal_name": "Cliente Sin Items",
        "items": [],
    }
    r = client.post("/api/quotations/create", json=payload, cookies=cookies_a, headers=_csrf_headers())
    assert r.status_code == 400


def test_should_fail_create_without_customer_name(client, cookies_a):
    payload = {
        "customer_rfc": "XAXX010101000",
        "customer_legal_name": "",
        "items": [{"description": "Algo", "quantity": 1, "unit_price": 100}],
    }
    r = client.post("/api/quotations/create", json=payload, cookies=cookies_a, headers=_csrf_headers())
    assert r.status_code == 400


# ---- List quotations ----

def test_should_list_quotations(client, cookies_a):
    r = client.get("/api/quotations", cookies=cookies_a)
    assert r.status_code == 200
    j = r.json()
    assert "items" in j
    assert "total" in j
    assert isinstance(j["items"], list)
    assert j["total"] >= 1


# ---- Get single quotation ----

def test_should_get_quotation_by_id(client, cookies_a):
    qid = _insert_quotation(ISSUER_A, "Get Test Client",
                             items=[{"description": "Item for get test", "quantity": 1, "unit_price": 500, "iva_rate": 0.16}])

    r = client.get(f"/api/quotations/{qid}", cookies=cookies_a)
    assert r.status_code == 200
    j = r.json()
    assert j["id"] == qid
    assert j["customer_legal_name"] == "Get Test Client"
    assert len(j["items"]) == 1
    assert j["items"][0]["description"] == "Item for get test"


def test_should_return_404_for_nonexistent_quotation(client, cookies_a):
    r = client.get("/api/quotations/999999", cookies=cookies_a)
    assert r.status_code == 404


# ---- Update status ----

def test_should_update_quotation_status(client, cookies_a):
    qid = _insert_quotation(ISSUER_A, "Status Test Client")

    # Update to sent
    r = client.post(
        "/api/quotations/update-status",
        json={"id": qid, "status": "sent"},
        cookies=cookies_a,
        headers=_csrf_headers(),
    )
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["data"]["status"] == "sent"


def test_should_fail_update_status_with_invalid_status(client, cookies_a):
    qid = _insert_quotation(ISSUER_A, "Invalid Status Client")

    r = client.post(
        "/api/quotations/update-status",
        json={"id": qid, "status": "nonsense"},
        cookies=cookies_a,
        headers=_csrf_headers(),
    )
    assert r.status_code == 400


# ---- Delete quotation ----

def test_should_delete_draft_quotation(client, cookies_a):
    qid = _insert_quotation(ISSUER_A, "Delete Test Client")

    r = client.delete(f"/api/quotations/{qid}", cookies=cookies_a, headers=_csrf_headers())
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["data"]["status"] == "deleted"

    # Verify it's actually deleted (status changed)
    get_r = client.get(f"/api/quotations/{qid}", cookies=cookies_a)
    assert get_r.status_code == 200
    assert get_r.json()["status"] == "deleted"


def test_should_delete_sent_quotation(client, cookies_a):
    qid = _insert_quotation(ISSUER_A, "Delete Sent Client", status="sent")

    r = client.delete(f"/api/quotations/{qid}", cookies=cookies_a, headers=_csrf_headers())
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "deleted"


def test_should_fail_delete_accepted_quotation(client, cookies_a):
    qid = _insert_quotation(ISSUER_A, "Accepted No Delete", status="accepted")

    r = client.delete(f"/api/quotations/{qid}", cookies=cookies_a, headers=_csrf_headers())
    assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"


def test_should_fail_delete_converted_quotation(client, cookies_a):
    qid = _insert_quotation(ISSUER_A, "Converted No Delete", status="converted")

    r = client.delete(f"/api/quotations/{qid}", cookies=cookies_a, headers=_csrf_headers())
    assert r.status_code == 400


def test_should_fail_delete_nonexistent_quotation(client, cookies_a):
    r = client.delete("/api/quotations/999999", cookies=cookies_a, headers=_csrf_headers())
    assert r.status_code == 400


# ---- Update items ----

def test_should_update_items_on_draft_quotation(client, cookies_a):
    qid = _insert_quotation(ISSUER_A, "Items Update Client",
                             items=[{"description": "Original item", "quantity": 1, "unit_price": 100, "iva_rate": 0.16}])

    # Update with new items
    new_items = [
        {"description": "Updated item 1", "quantity": 3, "unit_price": 500, "iva_rate": 0.16},
        {"description": "Updated item 2", "quantity": 1, "unit_price": 2000, "iva_rate": 0.08},
    ]
    r = client.put(f"/api/quotations/{qid}/items", json=new_items, cookies=cookies_a, headers=_csrf_headers())
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    assert len(j["data"]["items"]) == 2
    assert j["data"]["items"][0]["description"] == "Updated item 1"
    assert j["data"]["items"][1]["description"] == "Updated item 2"

    # Verify subtotal/total are computed correctly
    # item 1: 3 * 500 = 1500, iva = 240
    # item 2: 1 * 2000 = 2000, iva = 160
    # subtotal = 3500, iva = 400, total = 3900
    assert j["data"]["subtotal"] == 3500.0
    assert j["data"]["iva_total"] == 400.0
    assert j["data"]["total"] == 3900.0

    # Verify via GET that items were replaced
    get_r = client.get(f"/api/quotations/{qid}", cookies=cookies_a)
    assert get_r.status_code == 200
    assert len(get_r.json()["items"]) == 2


def test_should_fail_update_items_on_sent_quotation(client, cookies_a):
    qid = _insert_quotation(ISSUER_A, "Sent No Edit", status="sent")

    new_items = [{"description": "Should fail", "quantity": 1, "unit_price": 999}]
    r = client.put(f"/api/quotations/{qid}/items", json=new_items, cookies=cookies_a, headers=_csrf_headers())
    assert r.status_code == 400


def test_should_fail_update_items_with_empty_list(client, cookies_a):
    qid = _insert_quotation(ISSUER_A, "Empty Items Client")

    r = client.put(f"/api/quotations/{qid}/items", json=[], cookies=cookies_a, headers=_csrf_headers())
    assert r.status_code == 400


def test_should_fail_update_items_on_nonexistent_quotation(client, cookies_a):
    new_items = [{"description": "Ghost item", "quantity": 1, "unit_price": 100}]
    r = client.put("/api/quotations/999999/items", json=new_items, cookies=cookies_a, headers=_csrf_headers())
    assert r.status_code == 400


# ---- Filter by status ----

def test_should_filter_quotations_by_status(client, cookies_a):
    # Insert a draft and a sent quotation directly
    _insert_quotation(ISSUER_A, "Filter draft client", customer_rfc="FILTER010101000", status="draft")
    _insert_quotation(ISSUER_A, "Filter sent client", customer_rfc="FILTER010101000", status="sent")

    # Filter by draft
    r = client.get("/api/quotations?status=draft", cookies=cookies_a)
    assert r.status_code == 200
    j = r.json()
    assert all(item["status"] == "draft" for item in j["items"])

    # Filter by sent
    r2 = client.get("/api/quotations?status=sent", cookies=cookies_a)
    assert r2.status_code == 200
    j2 = r2.json()
    assert all(item["status"] == "sent" for item in j2["items"])


def test_should_filter_quotations_by_customer_rfc(client, cookies_a):
    unique_rfc = "UNIQUERFC01000"
    _insert_quotation(ISSUER_A, "Unique RFC Client", customer_rfc=unique_rfc)

    r = client.get(f"/api/quotations?customer_rfc={unique_rfc}", cookies=cookies_a)
    assert r.status_code == 200
    j = r.json()
    assert j["total"] >= 1
    assert all(item["customer_rfc"] == unique_rfc for item in j["items"])


def test_should_filter_quotations_by_date_range(client, cookies_a):
    # All quotations created today should be found with a wide date range
    r = client.get("/api/quotations?date_from=2020-01-01&date_to=2099-12-31", cookies=cookies_a)
    assert r.status_code == 200
    j = r.json()
    assert j["total"] >= 1

    # No quotations from the future
    r2 = client.get("/api/quotations?date_from=2099-01-01", cookies=cookies_a)
    assert r2.status_code == 200
    assert r2.json()["total"] == 0


# ---- Cross-tenant isolation ----

def test_should_not_allow_tenant_b_to_see_tenant_a_quotations(client, cookies_a, cookies_b):
    qid_a = _insert_quotation(ISSUER_A, "Tenant A Isolation")

    # Tenant B should not be able to GET it
    r = client.get(f"/api/quotations/{qid_a}", cookies=cookies_b)
    assert r.status_code == 404

    # Tenant B's list should not include it
    r_list = client.get("/api/quotations", cookies=cookies_b)
    assert r_list.status_code == 200
    ids = [item["id"] for item in r_list.json()["items"]]
    assert qid_a not in ids


def test_should_not_allow_tenant_b_to_delete_tenant_a_quotation(client, cookies_a, cookies_b):
    # Insert directly to avoid rate limiting
    conn = db()
    try:
        conn.execute(
            "INSERT INTO quotations (issuer_id, customer_rfc, customer_legal_name, status, public_token, created_at, updated_at) "
            "VALUES (?, 'XAXX010101000', 'Isolation Delete Test', 'draft', 'iso_del_tok', datetime('now'), datetime('now'))",
            (ISSUER_A,),
        )
        qid_a = conn.execute("SELECT last_insert_rowid() AS rid").fetchone()["rid"]
        conn.commit()
    finally:
        conn.close()

    # Tenant B cannot delete tenant A's quotation
    r = client.delete(f"/api/quotations/{qid_a}", cookies=cookies_b, headers=_csrf_headers())
    assert r.status_code == 400  # "not found" from the tenant-scoped query


def test_should_not_allow_tenant_b_to_update_items_of_tenant_a(client, cookies_a, cookies_b):
    # Insert directly to avoid rate limiting
    conn = db()
    try:
        conn.execute(
            "INSERT INTO quotations (issuer_id, customer_rfc, customer_legal_name, status, public_token, created_at, updated_at) "
            "VALUES (?, 'XAXX010101000', 'Isolation Items Test', 'draft', 'iso_item_tok', datetime('now'), datetime('now'))",
            (ISSUER_A,),
        )
        qid_a = conn.execute("SELECT last_insert_rowid() AS rid").fetchone()["rid"]
        conn.commit()
    finally:
        conn.close()

    # Tenant B cannot update items of tenant A's quotation
    new_items = [{"description": "Hacked item", "quantity": 99, "unit_price": 0.01}]
    r = client.put(f"/api/quotations/{qid_a}/items", json=new_items, cookies=cookies_b, headers=_csrf_headers())
    assert r.status_code == 400  # "not found" from the tenant-scoped query


# ---- CSRF protection ----

def test_should_fail_delete_without_csrf(client, cookies_a):
    # Insert a draft quotation directly to avoid rate limiting
    conn = db()
    try:
        conn.execute(
            "INSERT INTO quotations (issuer_id, customer_rfc, customer_legal_name, status, public_token, created_at, updated_at) "
            "VALUES (?, 'XAXX010101000', 'CSRF Test', 'draft', 'csrf_del_tok', datetime('now'), datetime('now'))",
            (ISSUER_A,),
        )
        qid = conn.execute("SELECT last_insert_rowid() AS rid").fetchone()["rid"]
        conn.commit()
    finally:
        conn.close()

    # No CSRF header
    r = client.delete(f"/api/quotations/{qid}", cookies=cookies_a)
    assert r.status_code == 403


def test_should_fail_update_items_without_csrf(client, cookies_a):
    # Insert a draft quotation directly to avoid rate limiting
    conn = db()
    try:
        conn.execute(
            "INSERT INTO quotations (issuer_id, customer_rfc, customer_legal_name, status, public_token, created_at, updated_at) "
            "VALUES (?, 'XAXX010101000', 'CSRF Items Test', 'draft', 'csrf_items_tok', datetime('now'), datetime('now'))",
            (ISSUER_A,),
        )
        qid = conn.execute("SELECT last_insert_rowid() AS rid").fetchone()["rid"]
        conn.execute(
            "INSERT INTO quotation_items (quotation_id, description, quantity, unit_price, iva_rate, sort_order) "
            "VALUES (?, 'Item', 1, 100, 0.16, 0)",
            (qid,),
        )
        conn.commit()
    finally:
        conn.close()

    new_items = [{"description": "New", "quantity": 1, "unit_price": 100}]
    r = client.put(f"/api/quotations/{qid}/items", json=new_items, cookies=cookies_a)
    assert r.status_code == 403
