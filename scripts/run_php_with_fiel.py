#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

# Raíz del proyecto
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from services.sat.subprocess_utils import run_php  # noqa: E402
from services.sat.sat_credentials_secure import decrypted_fiel_env  # noqa: E402


def main(argv: list[str]) -> int:
    """
    Wrapper para ejecutar scripts PHP que requieren FIEL (credenciales SAT).

    Uso:
      python3 scripts/run_php_with_fiel.py <php_script> <issuer_id> [args...]
    """
    if len(argv) < 3:
        print("Uso: python3 scripts/run_php_with_fiel.py <php_script> <issuer_id> [args...]", file=sys.stderr)
        return 2

    php_script = argv[1]
    issuer_id = int(argv[2])
    args = argv[1:]  # incluye script como primer arg para run_php

    env = os.environ.copy()
    env.setdefault("APP_DB_PATH", os.getenv("APP_DB_PATH") or os.path.join(BASE_DIR, "invoicing.db"))

    with decrypted_fiel_env(issuer_id) as fiel_env:
        env.update(fiel_env)
        stdout, stderr = run_php(args, env=env, cwd=BASE_DIR, timeout=int(os.getenv("PHP_TIMEOUT", "600")))
        if stdout:
            sys.stdout.write(stdout)
        if stderr:
            sys.stderr.write(stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

