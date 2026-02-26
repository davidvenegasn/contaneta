"""
Test de import básico: verifica que la aplicación y la configuración cargan sin error.
Útil para CI o smoke de código (no requiere servidor ni DB).

Uso:
  python -m tests.test_import
  python tests/test_import.py
  pytest tests/test_import.py   # si pytest está instalado
"""
import sys
from pathlib import Path

# Raíz del proyecto
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_import_config():
    import config
    assert hasattr(config, "BASE_DIR")
    assert hasattr(config, "DB_PATH")
    assert hasattr(config, "ENV")


def test_import_app():
    import app
    assert app.app is not None
    assert hasattr(app.app, "routes")


def test_health_route_exists():
    import app
    routes = [r.path for r in app.app.routes if hasattr(r, "path")]
    assert "/health" in routes or any("/health" in str(r) for r in app.app.routes)


if __name__ == "__main__":
    test_import_config()
    test_import_app()
    test_health_route_exists()
    print("OK: imports básicos pasaron.")
