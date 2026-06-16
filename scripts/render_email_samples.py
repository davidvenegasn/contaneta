#!/usr/bin/env python3
"""Render all email templates with mock data and save to tmp/email_samples/.

Usage:
    python scripts/render_email_samples.py

Output: tmp/email_samples/<template_name>.html and .txt for each template.
"""
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.email.templates import render

SAMPLES = {
    "welcome": {
        "brand_name": "ContaNeta",
        "user_name": "María López",
        "onboarding_url": "https://app.contaneta.com/portal/onboarding",
    },
    "trial_expiring": {
        "days_until_expiry": 3,
        "trial_expires_at": "20 de junio de 2026",
        "pricing_url": "https://app.contaneta.com/pricing",
    },
    "payment_failed": {
        "brand_name": "ContaNeta",
        "failure_reason": "Tarjeta declinada por fondos insuficientes",
        "amount": 499.00,
        "billing_url": "https://app.contaneta.com/portal/billing",
    },
    "email_verification": {
        "verification_url": "https://app.contaneta.com/verify?token=abc123def456",
    },
    "password_reset": {
        "reset_url": "https://app.contaneta.com/reset?token=xyz789abc012",
    },
    "invoice_sent": {
        "from_name": "Empresa ABC SA de CV",
        "total": 11600.00,
        "currency": "MXN",
        "serie": "A",
        "folio": "123",
        "fecha_emision": "15 de junio de 2026",
        "uuid": "abc12345-6789-0000-aaaa-bbbbccccdddd",
    },
    "declaration_summary": {
        "periodo": "Mayo 2026",
        "user_name": "Juan Pérez",
        "tipo_declaracion": "Mensual ISR",
        "saldo_a_cargo": 15230.50,
        "saldo_a_favor": 0,
        "linea_captura": "0012345678901234567890",
        "fecha_vencimiento": "17 de junio de 2026",
        "folio_acuse": "AC-2026-05-001",
        "portal_url": "https://app.contaneta.com/portal/declaraciones/1",
        "brand_name": "ContaNeta",
    },
    "csd_expiring": {
        "expires_at": "1 de julio de 2026",
        "days_until_expiry": 15,
        "brand_name": "ContaNeta",
        "settings_url": "https://app.contaneta.com/portal/settings",
    },
    "fiel_expiring": {
        "expires_at": "15 de julio de 2026",
        "days_until_expiry": 29,
        "brand_name": "ContaNeta",
        "settings_url": "https://app.contaneta.com/portal/settings",
    },
    "subscription_renewed": {
        "brand_name": "ContaNeta",
        "plan_name": "Profesional",
        "next_billing_date": "15 de julio de 2026",
    },
}


def main():
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tmp", "email_samples")
    os.makedirs(out_dir, exist_ok=True)

    for name, context in SAMPLES.items():
        html, text = render(name, context)
        html_path = os.path.join(out_dir, f"{name}.html")
        txt_path = os.path.join(out_dir, f"{name}.txt")
        with open(html_path, "w") as f:
            f.write(html)
        with open(txt_path, "w") as f:
            f.write(text)
        print(f"  {name}.html ({len(html)} bytes) + .txt ({len(text)} bytes)")

    print(f"\nSaved {len(SAMPLES)} email samples to {out_dir}/")


if __name__ == "__main__":
    main()
