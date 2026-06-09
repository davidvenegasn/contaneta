"""One-shot fix: push legal_info (razon_social + regimen_fiscal + fiscal_zip)
to Facturapi for issuers that have an org_id but never received the legal info
update. This is what moves orgs from "generic test mode" to "live-ready".

Usage:
    # Fix one issuer interactively (asks for CP fiscal if missing in DB)
    .venv/bin/python scripts/fix_facturapi_legal_info.py --issuer-id 100640

    # Fix all issuers that have org but no legal_info pushed
    .venv/bin/python scripts/fix_facturapi_legal_info.py --all

    # Provide CP fiscal explicitly (saves to DB then pushes)
    .venv/bin/python scripts/fix_facturapi_legal_info.py --issuer-id 100640 --zip 64986
"""
from __future__ import annotations

import argparse
import sys

from database import db
from services.facturapi.provision import push_legal_info_to_facturapi


def update_zip_in_db(issuer_id: int, zip_code: str) -> None:
    if not zip_code.isdigit() or len(zip_code) != 5:
        raise SystemExit(f"CP fiscal inválido: {zip_code!r} (debe ser 5 dígitos)")
    conn = db()
    try:
        conn.execute(
            "UPDATE issuers SET fiscal_zip = ?, updated_at = datetime('now') WHERE id = ?",
            (zip_code, issuer_id),
        )
        conn.commit()
    finally:
        conn.close()


def list_issuers_needing_push() -> list[dict]:
    conn = db()
    try:
        rows = conn.execute(
            """SELECT id, rfc, razon_social, regimen_fiscal, facturapi_org_id, fiscal_zip
               FROM issuers
               WHERE active = 1
                 AND facturapi_org_id IS NOT NULL AND facturapi_org_id != ''
               ORDER BY id"""
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issuer-id", type=int, help="Process only this issuer")
    parser.add_argument("--zip", type=str, help="Set fiscal_zip before pushing (5 digits)")
    parser.add_argument("--all", action="store_true", help="Process all issuers with org_id")
    args = parser.parse_args()

    if not args.issuer_id and not args.all:
        parser.error("Pass --issuer-id <id> or --all")

    if args.issuer_id and args.zip:
        update_zip_in_db(args.issuer_id, args.zip)
        print(f"✓ DB updated: issuer {args.issuer_id} fiscal_zip = {args.zip}")

    rows = list_issuers_needing_push()
    if args.issuer_id:
        rows = [r for r in rows if r["id"] == args.issuer_id]

    if not rows:
        print("No issuers found matching criteria.")
        return 0

    print(f"Processing {len(rows)} issuer(s):\n")
    ok_count = 0
    fail_count = 0
    for row in rows:
        issuer_id = row["id"]
        missing = []
        if not (row.get("razon_social") or "").strip(): missing.append("razon_social")
        if not (row.get("regimen_fiscal") or "").strip(): missing.append("regimen_fiscal")
        if not (row.get("fiscal_zip") or "").strip(): missing.append("fiscal_zip")
        if missing:
            print(f"  ⚠ issuer {issuer_id} ({row['rfc']}): faltan en DB: {', '.join(missing)}")
            if "fiscal_zip" in missing:
                print(f"    → Re-ejecuta con: --issuer-id {issuer_id} --zip 12345")
            continue
        try:
            push_legal_info_to_facturapi(issuer_id)
            print(f"  ✓ issuer {issuer_id} ({row['rfc']}) → org {row['facturapi_org_id']}")
            ok_count += 1
        except Exception as e:
            print(f"  ✗ issuer {issuer_id}: {e}")
            fail_count += 1

    print(f"\nDone: {ok_count} ok, {fail_count} failed")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
