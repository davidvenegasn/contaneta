"""
Wrapper único para subprocess con timeout obligatorio.
Evita bloqueos por procesos que no terminan (PHP SAT, scripts de backup, etc.).
"""
import logging
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_PHP_TIMEOUT = 60
DEFAULT_QUICK_TIMEOUT = 30
DEFAULT_SYNC_TIMEOUT = 600


def run_cmd(
    cmd: list[str],
    *,
    timeout: int = DEFAULT_PHP_TIMEOUT,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    capture_output: bool = True,
    text: bool = True,
) -> tuple[str, str, int]:
    """
    Ejecuta cmd con timeout. Nunca ejecuta sin timeout.
    Returns: (stdout, stderr, returncode).
    Lanza subprocess.TimeoutExpired si se supera el timeout.
    """
    try:
        r = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=capture_output,
            text=text,
            timeout=timeout,
        )
        out = (r.stdout or "").strip() if capture_output else ""
        err = (r.stderr or "").strip() if capture_output else ""
        if r.returncode != 0:
            logger.debug("run_cmd exit %s: %s", r.returncode, err or out)
        return out, err, r.returncode
    except subprocess.TimeoutExpired as e:
        logger.warning("run_cmd timeout after %ss: %s", timeout, cmd[:2])
        raise
    except FileNotFoundError:
        logger.warning("run_cmd: command not found %s", cmd[0] if cmd else "?")
        raise


def run_php(
    args: list[str],
    *,
    timeout: int = DEFAULT_PHP_TIMEOUT,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    php_bin: str = "php",
) -> tuple[str, str, int]:
    """
    Ejecuta php con los argumentos dados. Siempre con timeout.
    Returns: (stdout, stderr, returncode).
    """
    cmd = [php_bin] + [str(a) for a in args]
    return run_cmd(cmd, timeout=timeout, cwd=cwd, env=env)
