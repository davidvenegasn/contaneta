from __future__ import annotations

import logging
import subprocess
from typing import Optional

from services.errors import ExternalServiceError


logger = logging.getLogger(__name__)


DEFAULT_PHP_TIMEOUT = 120


def run_cmd(
    args: list[str],
    *,
    timeout: int,
    env: Optional[dict] = None,
    cwd: Optional[str] = None,
) -> tuple[str, str]:
    """
    Ejecuta un comando con timeout y captura de stdout/stderr.

    - En error/timeout: lanza ExternalServiceError con public_message consistente.
    - En éxito: retorna (stdout, stderr) como strings (sin strip agresivo).
    """
    if not args:
        raise ValueError("args vacío")
    try:
        proc = subprocess.Popen(
            [str(a) for a in args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
            env=env,
        )
        try:
            stdout_data, stderr_data = proc.communicate(timeout=int(timeout))
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise
        r = subprocess.CompletedProcess(
            args=proc.args, returncode=proc.returncode,
            stdout=stdout_data, stderr=stderr_data,
        )
    except subprocess.TimeoutExpired as e:
        logger.exception("subprocess timeout (killed): %s", args[:2])
        raise ExternalServiceError(
            code="SUBPROCESS_TIMEOUT",
            public_message="No pudimos completar la acción con SAT. Intenta de nuevo.",
            internal_message=str(e),
        )
    except FileNotFoundError as e:
        logger.exception("subprocess not found: %s", args[:1])
        raise ExternalServiceError(
            code="SUBPROCESS_NOT_FOUND",
            public_message="No pudimos completar la acción con SAT. Intenta de nuevo.",
            internal_message=str(e),
        )
    except Exception as e:
        logger.exception("subprocess error: %s", args[:2])
        raise ExternalServiceError(
            code="SUBPROCESS_ERROR",
            public_message="No pudimos completar la acción con SAT. Intenta de nuevo.",
            internal_message=str(e),
        )

    stdout = r.stdout or ""
    stderr = r.stderr or ""
    if r.returncode != 0:
        logger.error("subprocess failed rc=%s cmd=%s", r.returncode, args[:2])
        detail = (stderr or stdout or f"returncode={r.returncode}").strip()
        raise ExternalServiceError(
            code="SUBPROCESS_FAILED",
            public_message="No pudimos completar la acción con SAT. Intenta de nuevo.",
            internal_message=detail[:2000],
            meta={"returncode": r.returncode},
        )
    return stdout, stderr


def run_php(
    args: list[str],
    *,
    timeout: int = DEFAULT_PHP_TIMEOUT,
    env: Optional[dict] = None,
    cwd: Optional[str] = None,
    php_bin: str = "php",
) -> tuple[str, str]:
    """
    Ejecuta PHP con timeout. `args` debe incluir el script y sus argumentos.
    """
    cmd = [php_bin] + [str(a) for a in args]
    return run_cmd(cmd, timeout=timeout, env=env, cwd=cwd)

