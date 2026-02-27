#!/usr/bin/env python3
"""
Smoke test: portal home, API customers/products, create customer/product vía API,
y verificación de que los datos aparecen (Factura rápida dropdowns se llenan vía API).

Uso:
  - Con servidor ya corriendo: python3 scripts/smoke_selfserve.py
  - BASE_URL=http://127.0.0.1:8000 PORTAL_SMOKE_TOKEN=demo python3 scripts/smoke_selfserve.py

Requisito: PORTAL_SMOKE_TOKEN (o DEV_TOKEN) debe ser un token de issuer_tokens que apunte a un issuer existente.
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

try:
    import requests
except ImportError:
    print("ERROR: Se requiere 'requests'. Instala con: pip install -r requirements.txt")
    sys.exit(1)


def _fail(step: str, expected: str, response: requests.Response, extra: str = ""):
    body = (response.text or response.content.decode("utf-8", errors="replace"))[:500]
    print(f"\n[FALLO] {step}")
    print(f"  Esperado: {expected}")
    print(f"  Status:  {response.status_code}")
    print(f"  URL:     {response.url}")
    if extra:
        print(f"  {extra}")
    print(f"  Respuesta (snippet):\n---\n{body}\n---")
    sys.exit(1)


def main():
    base_url = (os.getenv("BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
    token = os.getenv("PORTAL_SMOKE_TOKEN") or os.getenv("DEV_TOKEN") or "demo"
    session = requests.Session()
    session.headers["User-Agent"] = "SmokeSelfServe/1.0"

    # --- 1. Sesión vía token (cookie) ---
    step = "1. GET /login?token=... (obtener sesión)"
    try:
        r = session.get(f"{base_url}/login", params={"token": token}, allow_redirects=True, timeout=10)
    except requests.RequestException as e:
        print(f"[FALLO] {step}: No se pudo conectar a {base_url}. {e}")
        sys.exit(1)
    if r.status_code not in (200, 302):
        _fail(step, "200 o 302", r)
    if "portal_session" not in session.cookies and "portal_session" not in str(session.cookies):
        _fail(step, "Cookie portal_session tras login con token", r, "Token puede ser inválido o DEV_MODE=0.")

    # --- 2. GET /portal/home ---
    step = "2. GET /portal/home"
    r = session.get(f"{base_url}/portal/home", timeout=10)
    if r.status_code != 200:
        _fail(step, "200", r)
    text = (r.text or "").strip()
    if "Factura rápida" not in text and "Inicio" not in text:
        _fail(step, "HTML con 'Factura rápida' o 'Inicio'", r)

    # --- 3. GET /api/customers ---
    step = "3. GET /api/customers"
    r = session.get(f"{base_url}/api/customers", timeout=10)
    if r.status_code != 200:
        _fail(step, "200", r)
    try:
        raw = r.json()
        customers = raw.get("items", raw) if isinstance(raw, dict) else raw
    except Exception:
        _fail(step, "JSON válido", r, "Respuesta no es JSON válido.")
    if not isinstance(customers, list):
        _fail(step, "items o array", r, f"Tipo recibido: {type(customers)}")

    # --- 4. GET /api/products ---
    step = "4. GET /api/products"
    r = session.get(f"{base_url}/api/products", timeout=10)
    if r.status_code != 200:
        _fail(step, "200", r)
    try:
        raw = r.json()
        products = raw.get("items", raw) if isinstance(raw, dict) else raw
    except Exception:
        _fail(step, "JSON válido", r, "Respuesta no es JSON válido.")
    if not isinstance(products, list):
        _fail(step, "items o array", r, f"Tipo recibido: {type(products)}")

    # --- 5. POST /api/customers/create ---
    step = "5. POST /api/customers/create"
    payload = {
        "rfc": "SMO960101XXX",
        "legal_name": "Smoke Test Cliente SA de CV",
        "alias": "Smoke cliente",
        "zip": "64000",
        "tax_system": "616",
        "email": "smoke@test.local",
    }
    r = session.post(
        f"{base_url}/api/customers/create",
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    if r.status_code not in (200, 201):
        _fail(step, "200 o 201", r)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not data.get("ok") and r.status_code == 200:
        _fail(step, "ok: true en respuesta", r, f"data={data}")

    # --- 6. POST /api/products/create ---
    step = "6. POST /api/products/create"
    payload = {
        "description": "Smoke test producto",
        "product_key": "80141600",
        "unit_key": "E48",
        "unit_price": 100.0,
        "iva_rate": 0.16,
    }
    r = session.post(
        f"{base_url}/api/products/create",
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    if r.status_code not in (200, 201):
        _fail(step, "200 o 201", r)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not data.get("ok") and r.status_code == 200:
        _fail(step, "ok: true en respuesta", r, f"data={data}")

    # --- 7. Verificar que dropdowns se llenarían (API devuelve clientes y productos) ---
    step = "7. GET /api/customers (verificar listado tras create)"
    r = session.get(f"{base_url}/api/customers", timeout=10)
    if r.status_code != 200:
        _fail(step, "200", r)
    raw = r.json()
    customers_after = raw.get("items", raw) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    if not any((c.get("rfc") or "").upper() == "SMO960101XXX" for c in customers_after):
        _fail(step, "Al menos un cliente con RFC SMO960101XXX", r, f"Clientes: {[c.get('rfc') for c in customers_after]}")

    step = "8. GET /api/products (verificar listado tras create)"
    r = session.get(f"{base_url}/api/products", timeout=10)
    if r.status_code != 200:
        _fail(step, "200", r)
    raw = r.json()
    products_after = raw.get("items", raw) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    if not any("Smoke test producto" in (p.get("description") or "") for p in products_after):
        _fail(step, "Al menos un producto con descripción 'Smoke test producto'", r, f"Productos: {[p.get('description') for p in products_after]}")

    print("OK. Smoke self-serve: portal home, API customers/products, create vía API, dropdowns (API) con datos.")
    sys.exit(0)


if __name__ == "__main__":
    main()
