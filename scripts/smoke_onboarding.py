#!/usr/bin/env python3
"""
Smoke test: registro (email+password) → confirmar perfil → onboarding (RFC) → login → GET /portal/home.

Ejecución:
  - Con servidor ya corriendo: python3 scripts/smoke_onboarding.py
  - Con servidor en puerto alterno: python3 scripts/smoke_onboarding.py --port 8010
  - Arrancar servidor temporalmente: python3 scripts/smoke_onboarding.py --start-server

Usa requests (requirements.txt). Si algo falla, imprime el paso, status esperado/real y un snippet de la respuesta.
"""
import argparse
import os
import re
import subprocess
import sys
import time

# Directorio raíz del proyecto (donde está app.py)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

try:
    import requests
except ImportError:
    print("ERROR: Se requiere 'requests'. Instala con: pip install -r requirements.txt")
    sys.exit(1)

# Texto que debe aparecer en la página del portal home para considerar éxito
PORTAL_HOME_MARKER = "ContaNeta"
PORTAL_HOME_ALT_MARKERS = ("Inicio", "Factura rápida", "Ingresos (sin IVA)")
SESSION_COOKIE_NAME = "portal_session"


def _fail(step: str, expected: str, response: requests.Response, extra: str = ""):
    """Imprime error claro y sale con código 1."""
    body = (response.text or response.content.decode("utf-8", errors="replace"))[:600]
    print(f"\n[FALLO] Paso: {step}")
    print(f"  Esperado: {expected}")
    print(f"  Status:  {response.status_code}")
    print(f"  URL:     {response.url}")
    if extra:
        print(f"  {extra}")
    print(f"  Respuesta (snippet):\n---\n{body}\n---")
    sys.exit(1)


def _check_ok(step: str, response: requests.Response, allowed=(200, 302)):
    if response.status_code not in allowed:
        _fail(step, f"Status en {allowed}", response)


def run_smoke(base_url: str, start_server: bool, port: int) -> None:
    proc = None
    if start_server:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            for _ in range(30):
                time.sleep(0.5)
                try:
                    r = requests.get(f"http://127.0.0.1:{port}/login", timeout=2)
                    if r.status_code in (200, 302):
                        break
                except requests.RequestException:
                    continue
            else:
                _, err = proc.communicate(timeout=2)
                print("ERROR: El servidor no respondió a tiempo.")
                if err:
                    print("stderr:", err[:800])
                proc.kill()
                sys.exit(1)
        except Exception as e:
            proc.kill()
            print(f"ERROR arrancando servidor: {e}")
            sys.exit(1)

    base = base_url.rstrip("/")
    session = requests.Session()
    session.headers["User-Agent"] = "SmokeOnboarding/1.0"
    # Email único para no chocar con registros previos
    email = f"smoke-{int(time.time())}@test.local"
    password = "SmokeTestPassword1"
    name = "Smoke Test User"
    rfc = "SMO960101XXX"
    razon_social = "Smoke Test SA de CV"

    # --- 1. Registro (signup) ---
    step = "1. POST /signup (registro)"
    r = session.post(
        f"{base}/signup",
        data={
            "login_type": "email",
            "email": email,
            "password": password,
            "password_confirm": password,
            "accept_terms": "on",
        },
        allow_redirects=True,
        timeout=15,
    )
    _check_ok(step, r)
    if SESSION_COOKIE_NAME not in session.cookies:
        _fail(step, f"Cookie '{SESSION_COOKIE_NAME}' tras registro", r, "No se estableció la cookie de sesión.")
    if "/confirmar-perfil" not in r.url and "/portal/home" not in r.url:
        _fail(step, "Redirección a /confirmar-perfil o /portal/home", r, f"URL final: {r.url}")

    # Si nos mandaron a portal/home es que ya tenía membership (raro); si no, confirmar perfil
    if "/confirmar-perfil" in r.url or "confirmar" in r.text.lower():
        # --- 2. Confirmar perfil (nombre + crear issuer placeholder) ---
        step = "2. POST /confirmar-perfil (nombre y issuer)"
        r = session.post(
            f"{base}/confirmar-perfil",
            data={"name": name},
            allow_redirects=True,
            timeout=15,
        )
        _check_ok(step, r)
        if "/portal/home" not in r.url and "/onboarding" not in r.url:
            _fail(step, "Redirección a /portal/home o /onboarding", r, f"URL final: {r.url}")

    # --- 3. Onboarding (RFC y razón social) ---
    step = "3. POST /onboarding (RFC)"
    r = session.get(f"{base}/onboarding", timeout=10)
    _check_ok(step, r, allowed=(200, 302))
    if r.status_code == 302 and "/portal/home" in r.headers.get("Location", ""):
        # Ya tenía RFC; seguir a portal
        r = session.get(f"{base}/portal/home", allow_redirects=True, timeout=10)
    else:
        r = session.post(
            f"{base}/onboarding",
            data={
                "rfc": rfc,
                "razon_social": razon_social,
                "regimen_fiscal": "616",
            },
            allow_redirects=True,
            timeout=15,
        )
    _check_ok(step, r)
    if "/portal/home" not in r.url:
        _fail(step, "Redirección a /portal/home", r, f"URL final: {r.url}")

    # --- 4. Login (sesión nueva: simular usuario que cierra y vuelve a entrar) ---
    step = "4. POST /login (inicio de sesión)"
    session.cookies.clear()
    r = session.post(
        f"{base}/login",
        data={
            "login_type": "credentials",
            "cred_type": "email",
            "email": email,
            "password": password,
        },
        allow_redirects=True,
        timeout=15,
    )
    _check_ok(step, r)
    if SESSION_COOKIE_NAME not in session.cookies:
        _fail(step, f"Cookie '{SESSION_COOKIE_NAME}' tras login", r)
    if "/portal/home" not in r.url and "/choose-issuer" not in r.url and "/confirmar-perfil" not in r.url:
        _fail(step, "Redirección a /portal/home (o choose-issuer/confirmar-perfil)", r, f"URL final: {r.url}")

    # Si nos mandan a elegir issuer, elegir el primero y seguir
    if "/choose-issuer" in r.url:
        r = session.get(f"{base}/choose-issuer", timeout=10)
        _check_ok("4b. GET /choose-issuer", r, allowed=(200,))
        # Botón: <button type="submit" value="{{ m.issuer_id }}" ...>
        match = re.search(r'<button[^>]+type="submit"[^>]+value="(\d+)"', r.text)
        if not match:
            match = re.search(r'value="(\d+)"[^>]*name="issuer_id"', r.text)
        if not match:
            _fail("4b. Elegir issuer", "Encontrar issuer_id en /choose-issuer", r)
        issuer_id = match.group(1)
        r = session.post(f"{base}/choose-issuer", data={"issuer_id": issuer_id}, allow_redirects=True, timeout=15)
        _check_ok("4b. POST /choose-issuer", r)
        if "/portal/home" not in r.url:
            _fail("4b. POST /choose-issuer", "Redirección a /portal/home", r, f"URL final: {r.url}")

    # --- 5. GET /portal/home ---
    step = "5. GET /portal/home"
    r = session.get(f"{base}/portal/home", timeout=10)
    if r.status_code != 200:
        _fail(step, "Status 200", r)
    text = (r.text or "").strip()
    if PORTAL_HOME_MARKER not in text and not any(m in text for m in PORTAL_HOME_ALT_MARKERS):
        _fail(
            step,
            f"HTML conteniendo '{PORTAL_HOME_MARKER}' o uno de {PORTAL_HOME_ALT_MARKERS}",
            r,
            "La página del portal no contiene el texto esperado.",
        )

    print("OK. Smoke onboarding: registro → confirmar perfil → onboarding (RFC) → login → /portal/home.")
    if proc is not None:
        proc.terminate()
        proc.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description="Smoke test: registro, login y acceso al portal.")
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Puerto del servidor (default 8000).",
    )
    parser.add_argument(
        "--start-server",
        action="store_true",
        help="Arrancar uvicorn en el puerto indicado antes de ejecutar el test.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="URL base (ej. http://127.0.0.1:8000). Por defecto se usa --port para construirla.",
    )
    args = parser.parse_args()
    base_url = args.base_url or f"http://127.0.0.1:{args.port}"
    # Asegurar que base_url no tenga trailing slash para consistencia
    if base_url.endswith("/"):
        base_url = base_url[:-1]

    run_smoke(base_url, args.start_server, args.port)


if __name__ == "__main__":
    main()
