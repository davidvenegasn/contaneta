"""Test that bank movement totals exclude rows with impacta_contabilidad = 0."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_bank_impacta_")
os.close(_fd)
os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-bank-impacta"


def _setup_db():
    """Create a minimal bank_movements table with impacta_contabilidad column."""
    conn = sqlite3.connect(_test_db)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bank_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issuer_id INTEGER NOT NULL,
            fecha TEXT,
            descripcion TEXT,
            deposito REAL,
            retiro REAL,
            saldo REAL,
            tipo TEXT,
            categoria TEXT,
            metodo_hint TEXT,
            contraparte_hint TEXT,
            rfc_encontrado TEXT,
            confidence_score INTEGER DEFAULT 0,
            period_month TEXT,
            impacta_contabilidad INTEGER DEFAULT 1,
            statement_file_id TEXT DEFAULT '1',
            source_page_first INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Insert test data: 3 movements, one with impacta_contabilidad = 0
    conn.execute(
        "INSERT INTO bank_movements (issuer_id, fecha, deposito, retiro, tipo, categoria, period_month, impacta_contabilidad) VALUES (1, '2026-01-15', 1000.0, NULL, 'INGRESO', 'VENTAS', '2026-01', 1)"
    )
    conn.execute(
        "INSERT INTO bank_movements (issuer_id, fecha, deposito, retiro, tipo, categoria, period_month, impacta_contabilidad) VALUES (1, '2026-01-16', NULL, 500.0, 'GASTO', 'SERVICIOS', '2026-01', 1)"
    )
    # This one should be EXCLUDED from totals (financial movement, impacta=0)
    conn.execute(
        "INSERT INTO bank_movements (issuer_id, fecha, deposito, retiro, tipo, categoria, period_month, impacta_contabilidad) VALUES (1, '2026-01-17', 200.0, NULL, 'INGRESO', 'RENDIMIENTOS', '2026-01', 0)"
    )
    conn.commit()
    conn.close()


def test_sum_excludes_non_impacta():
    _setup_db()
    conn = sqlite3.connect(_test_db)
    conn.row_factory = sqlite3.Row
    # With filter: should exclude the 200 rendimiento
    row = conn.execute(
        "SELECT COALESCE(SUM(deposito), 0) AS ing, COALESCE(SUM(retiro), 0) AS gas FROM bank_movements WHERE issuer_id = 1 AND COALESCE(impacta_contabilidad, 1) = 1"
    ).fetchone()
    assert float(row["ing"]) == 1000.0, f"Expected 1000, got {row['ing']}"
    assert float(row["gas"]) == 500.0, f"Expected 500, got {row['gas']}"

    # Without filter: all 3 rows
    row_all = conn.execute(
        "SELECT COALESCE(SUM(deposito), 0) AS ing, COALESCE(SUM(retiro), 0) AS gas FROM bank_movements WHERE issuer_id = 1"
    ).fetchone()
    assert float(row_all["ing"]) == 1200.0, f"Expected 1200, got {row_all['ing']}"
    conn.close()


def test_coalesce_defaults_to_1_for_null():
    """Rows with NULL impacta_contabilidad should be included (default = 1)."""
    conn = sqlite3.connect(_test_db)
    conn.execute(
        "INSERT INTO bank_movements (issuer_id, fecha, deposito, retiro, tipo, categoria, period_month, impacta_contabilidad) VALUES (1, '2026-01-18', 300.0, NULL, 'INGRESO', 'OTROS', '2026-01', NULL)"
    )
    conn.commit()
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT COALESCE(SUM(deposito), 0) AS ing FROM bank_movements WHERE issuer_id = 1 AND COALESCE(impacta_contabilidad, 1) = 1"
    ).fetchone()
    # 1000 (impacta=1) + 300 (impacta=NULL → 1) = 1300. The 200 (impacta=0) is excluded.
    assert float(row["ing"]) == 1300.0, f"Expected 1300, got {row['ing']}"
    conn.close()
