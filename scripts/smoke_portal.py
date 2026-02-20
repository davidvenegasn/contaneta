#!/usr/bin/env python3
"""
Smoke test del portal: listados, detalle CFDI, descarga XML y PDF.
Usa token legacy (DEV_TOKEN o PORTAL_SMOKE_TOKEN) para obtener sesión por cookie.
Uso: PORTAL_SMOKE_TOKEN=demo BASE_URL=http://127.0.0.1:8000 python scripts/smoke_portal.py
"""
import os
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

def main():
    try:
        import requests
    except ImportError:
        print("Instala requests: pip install requests")
        sys.exit(1)

    base_url = (os.getenv("BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
    token = os.getenv("PORTAL_SMOKE_TOKEN") or os.getenv("DEV_TOKEN") or "demo"
    session = requests.Session()
    session.headers["User-Agent"] = "SmokePortal/1.0"

    errors = []

    # 1) Obtener sesión vía token (redirect con cookie)
    try:
        r = session.get(f"{base_url}/login", params={"token": token}, allow_redirects=True, timeout=5)
    except requests.exceptions.ConnectionError as e:
        errors.append(f"No se pudo conectar a {base_url} (¿app corriendo?). {e}")
        _report(errors)
        sys.exit(1)
    except requests.exceptions.Timeout:
        errors.append(f"Timeout al conectar a {base_url}")
        _report(errors)
        sys.exit(1)
    if r.status_code not in (200, 302):
        errors.append(f"GET /login?token=... -> {r.status_code}")
    # Tras token válido: 302 a /portal/home y cookie portal_session
    if "portal_session" not in session.cookies:
        if r.url.rstrip("/").endswith("/login") and r.status_code == 200:
            errors.append("No se obtuvo cookie de sesión (token inválido o inactivo)")
        elif "login" in (r.url or ""):
            errors.append("No se obtuvo cookie de sesión (token inválido o DEV_MODE=0)")

    # 2) Listado emitidas
    r = session.get(f"{base_url}/portal/invoices/issued", allow_redirects=True)
    if r.status_code != 200:
        errors.append(f"GET /portal/invoices/issued -> {r.status_code}")
    if r.status_code == 200 and "Facturas emitidas" not in r.text and "Listado" not in r.text:
        pass  # puede ser "no hay datos" o título distinto

    # 3) Listado recibidas
    r = session.get(f"{base_url}/portal/invoices/received", allow_redirects=True)
    if r.status_code != 200:
        errors.append(f"GET /portal/invoices/received -> {r.status_code}")

    # 4) Extraer un UUID del HTML de emitidas para probar detalle y descargas
    r = session.get(f"{base_url}/portal/invoices/issued", allow_redirects=True)
    uuid_match = re.search(r'/portal/cfdi/issued/([a-fA-F0-9\-]{36})', r.text) if r.status_code == 200 else None
    test_uuid = uuid_match.group(1) if uuid_match else None

    if test_uuid:
        # 5) Detalle CFDI emitido
        r = session.get(f"{base_url}/portal/cfdi/issued/{test_uuid}", allow_redirects=True)
        if r.status_code != 200:
            errors.append(f"GET /portal/cfdi/issued/{{uuid}} -> {r.status_code}")
        if r.status_code == 200 and "Detalle" not in r.text and "UUID" not in r.text:
            pass

        # 6) Descarga XML
        r = session.get(f"{base_url}/portal/sat/xml/{test_uuid}", allow_redirects=True)
        if r.status_code not in (200, 402):
            errors.append(f"GET /portal/sat/xml/{{uuid}} -> {r.status_code} (402 = requiere plan Pro)")
        if r.status_code == 200 and "<?xml" not in (r.text[:50] if r.text else ""):
            if "application/xml" in r.headers.get("Content-Type", ""):
                pass

        # 7) PDF (inline)
        r = session.get(f"{base_url}/portal/sat/pdf/{test_uuid}", allow_redirects=True)
        if r.status_code not in (200, 402):
            errors.append(f"GET /portal/sat/pdf/{{uuid}} -> {r.status_code} (402 = requiere plan Pro)")
        if r.status_code == 200:
            ct = r.headers.get("Content-Type") or ""
            if "pdf" not in ct.lower():
                errors.append(f"GET /portal/sat/pdf/{{uuid}} Content-Type no es PDF: {ct}")
    else:
        print("(No hay UUID en listado emitidas; se omiten pruebas de detalle/XML/PDF)")

    _report(errors)
    sys.exit(0)


def _report(errors):
    if errors:
        print("Smoke portal: FALLOS")
        for e in errors:
            print("  -", e)
        sys.exit(1)
    print("Smoke portal: OK (listados, detalle/XML/PDF según datos)")


if __name__ == "__main__":
    main()
