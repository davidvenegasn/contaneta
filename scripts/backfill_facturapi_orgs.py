"""Backfill: create Facturapi organizations for all existing issuers that
don't have one.

Run once after deploying the sync provisioning change. Idempotent: skips
issuers that already have `facturapi_org_id` set. Safe to re-run if some
fail (e.g. Facturapi was rate-limiting); just run again later.

Usage:
    .venv/bin/python scripts/backfill_facturapi_orgs.py
    .venv/bin/python scripts/backfill_facturapi_orgs.py --dry-run
    .venv/bin/python scripts/backfill_facturapi_orgs.py --issuer-id 100640
"""
from __future__ import annotations

import argparse
import sys
import time

from database import db
from services.facturapi.provision import ensure_provisioned
from services.facturapi import orgs as fpi_orgs


def list_pending_issuers(only_id: int | None = None) -> list[dict]:
    conn = db()
    try:
        if only_id:
            rows = conn.execute(
                """SELECT id, rfc, razon_social, facturapi_org_id
                   FROM issuers WHERE id = ? AND active = 1""",
                (only_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, rfc, razon_social, facturapi_org_id
                   FROM issuers
                   WHERE active = 1
                     AND (facturapi_org_id IS NULL OR facturapi_org_id = '')
                   ORDER BY id"""
            ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="List issuers without provisioning")
    parser.add_argument("--issuer-id", type=int, default=None, help="Provision only this issuer")
    parser.add_argument("--sleep", type=float, default=0.5, help="Seconds between API calls (rate-limit guard)")
    args = parser.parse_args()

    pending = list_pending_issuers(only_id=args.issuer_id)
    if not pending:
        print("✓ All active issuers already have a Facturapi org. Nothing to do.")
        return 0

    print(f"Found {len(pending)} issuer(s) without facturapi_org_id:")
    for row in pending:
        print(f"  - id={row['id']} rfc={row['rfc']} razon_social={row['razon_social']!r}")

    if args.dry_run:
        print("\n(dry-run: not provisioning)")
        return 0

    print()
    ok_count = 0
    fail_count = 0
    for row in pending:
        issuer_id = row["id"]
        try:
            result = ensure_provisioned(issuer_id)
            if result.get("already_provisioned"):
                print(f"  ↷ id={issuer_id}: already provisioned ({result['org_id']})")
            else:
                print(f"  ✓ id={issuer_id}: created org {result['org_id']}")
            ok_count += 1
        except fpi_orgs.FacturapiOrgsError as e:
            print(f"  ✗ id={issuer_id}: Facturapi error — {e}")
            fail_count += 1
        except Exception as e:
            print(f"  ✗ id={issuer_id}: unexpected error — {e}")
            fail_count += 1
        if args.sleep > 0:
            time.sleep(args.sleep)

    print(f"\nDone: {ok_count} ok, {fail_count} failed")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
