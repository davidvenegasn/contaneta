#!/usr/bin/env python3
"""Performance audit: DB stats, table sizes, slow query candidates, index coverage."""
import os
import sqlite3
import sys
import time

DB_PATH = os.getenv("APP_DB_PATH", "invoicing.db")


def main():
    if not os.path.isfile(DB_PATH):
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    print("=" * 60)
    print(f"ContaNeta Performance Audit — {DB_PATH}")
    print("=" * 60)

    # DB file size
    size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
    print(f"\nDB file size: {size_mb:.1f} MB")

    # WAL mode check
    journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    print(f"Journal mode: {journal}")

    # Page stats
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    page_count = conn.execute("PRAGMA page_count").fetchone()[0]
    freelist = conn.execute("PRAGMA freelist_count").fetchone()[0]
    print(f"Page size: {page_size}, Pages: {page_count}, Free: {freelist}")
    if freelist > page_count * 0.2:
        print("  WARNING: >20% free pages — consider VACUUM")

    # Table sizes
    print("\n--- Table Sizes ---")
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()]

    rows_data = []
    for t in tables:
        try:
            count = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            rows_data.append((t, count))
        except Exception:
            rows_data.append((t, -1))

    rows_data.sort(key=lambda x: x[1], reverse=True)
    for t, count in rows_data:
        print(f"  {t:40s} {count:>10,d} rows")

    # Index count per table
    print("\n--- Index Coverage ---")
    for t in tables:
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=? AND name NOT LIKE 'sqlite_%'",
            (t,)
        ).fetchall()
        idx_names = [r[0] for r in indexes]
        if idx_names:
            print(f"  {t}: {len(idx_names)} indexes")
        else:
            count = dict(rows_data).get(t, 0)
            if count > 100:
                print(f"  {t}: NO INDEXES (has {count:,d} rows — consider adding)")

    # Check for tables without issuer_id (multi-tenant risk)
    print("\n--- Multi-Tenant Isolation Check ---")
    for t in tables:
        cols = [r["name"] for r in conn.execute(f'PRAGMA table_info("{t}")').fetchall()]
        if "issuer_id" not in cols and t not in (
            "schema_migrations", "users", "issuers", "email_verifications",
            "password_resets", "memberships", "subscriptions", "audit_log",
        ):
            count = dict(rows_data).get(t, 0)
            if count > 0:
                print(f"  WARNING: {t} has no issuer_id column ({count:,d} rows)")

    # Quick query benchmark
    print("\n--- Query Benchmarks ---")
    benchmarks = [
        ("Health check (DB read)", "SELECT 1"),
        ("Count sat_cfdi", "SELECT COUNT(*) FROM sat_cfdi"),
        ("Count bank_movements", "SELECT COUNT(*) FROM bank_movements"),
        ("Count customer_profiles", "SELECT COUNT(*) FROM customer_profiles"),
    ]
    for label, sql in benchmarks:
        try:
            start = time.perf_counter()
            conn.execute(sql).fetchone()
            elapsed = (time.perf_counter() - start) * 1000
            status = "OK" if elapsed < 100 else "SLOW"
            print(f"  {label:40s} {elapsed:6.1f}ms  [{status}]")
        except Exception as e:
            print(f"  {label:40s} ERROR: {e}")

    # Integrity check
    print("\n--- Integrity Check ---")
    result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"  Result: {result}")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
