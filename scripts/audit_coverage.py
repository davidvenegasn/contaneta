#!/usr/bin/env python3
"""
Audit script: analiza el repo y genera AUDIT_COVERAGE_REPORT.md con patrones
de estabilidad (400/500 crudos, fetch sin helper, logging.exception sin rethrow, etc.).
Solo lectura; no modifica código. Debe correr en < 3s.
Uso: python scripts/audit_coverage.py [--fail-on-issues]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Carpetas a ignorar (no recorrer)
IGNORE_DIRS = {".venv", "node_modules", "storage", "keys", "dist", "build", "__pycache__", ".git"}

# Extensiones a analizar
EXTENSIONS = {".py", ".js", ".html"}

# ui.js define portalFetchWithTimeout; no marcar sus fetch como problema
HELPER_DEFINITION_FILE = "static/js/ui.js"


def should_skip_dir(name: str) -> bool:
    return name in IGNORE_DIRS or name.startswith(".")


def collect_files(root: Path) -> list[tuple[Path, str]]:
    """Devuelve lista de (path_abs, path_rel) con extensiones permitidas."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]
        rel_dir = os.path.relpath(dirpath, root) if dirpath != root else "."
        for f in filenames:
            ext = os.path.splitext(f)[1].lower()
            if ext not in EXTENSIONS:
                continue
            full = os.path.join(dirpath, f)
            rel = os.path.join(rel_dir, f).replace("\\", "/")
            if "audit_coverage.py" in rel:
                continue  # no auditar este script
            out.append((Path(full), rel))
    return out


# ----- Backend Python patterns -----

def backend_patterns() -> list[tuple[str, str, str]]:
    """(name, regex_or_keyword, category). category: critical | warning."""
    return [
        ("html_response_400", r"HTMLResponse\s*\([^)]*status_code\s*=\s*400", "critical"),
        ("html_response_str_e", r"HTMLResponse\s*\([^)]*(?:str\s*\(\s*e\s*\)|detail\s*=\s*str\s*\(\s*e\s*\)|f[\'\"]\{.*e\})", "critical"),
        ("return_400_with_exception", r"return\s+.*Response.*400|status_code\s*=\s*400", "critical"),
        ("http_exception_400_detail_str_e", r"HTTPException\s*\(\s*[^,]*400[^)]*detail\s*=\s*str\s*\(\s*e\s*\)", "critical"),
        ("except_exception_return_response", r"except\s+(Exception|\w+Exception)\s+as\s+\w+.*\n.*return\s+.*(?:Response|HTMLResponse)", "critical"),
        ("logging_exception_no_raise", r"logging\.exception\s*\([^)]+\)\s*\n\s*(?!raise|re-raise|reraise)", "warning"),
        ("subprocess_run_no_timeout", r"subprocess\.run\s*\([^)]*(?<!timeout\s*=\s*\d)[^)]*\)", "warning"),
    ]


def check_python_file(path: Path, rel: str, lines: list[str]) -> list[dict]:
    findings = []
    for i, line in enumerate(lines, 1):
        # status_code=400 y HTMLResponse en mismo bloque (misma línea o contexto)
        if "status_code=400" in line and "HTMLResponse" in line:
            findings.append({
                "file": rel,
                "line": i,
                "match": "HTMLResponse + status_code=400",
                "snippet": _snippet(lines, i),
                "category": "critical",
            })
        if "HTMLResponse" in line and ("str(e)" in line or "detail=str(e)" in line or 'f"{e}' in line or "f'{e}" in line):
            findings.append({
                "file": rel,
                "line": i,
                "match": "HTMLResponse con str(e) o detail=str(e)",
                "snippet": _snippet(lines, i),
                "category": "critical",
            })
        if "HTTPException" in line and "400" in line and ("str(e)" in line or "detail=str(e)" in line):
            findings.append({
                "file": rel,
                "line": i,
                "match": "HTTPException(400 con detail=str(e)",
                "snippet": _snippet(lines, i),
                "category": "critical",
            })
        if "logging.exception" in line:
            # no marcar si estamos en un exception_handler (ej. app.py server_error_handler)
            ctx_before = "\n".join(lines[max(0, i - 25) : i])
            if "exception_handler" in ctx_before or "def server_error_handler" in ctx_before:
                continue
            block = "\n".join(lines[i : min(len(lines), i + 5)])
            if not re.search(r"\braise\b", block):
                findings.append({
                    "file": rel,
                    "line": i,
                    "match": "logging.exception sin raise en bloque",
                    "snippet": _snippet(lines, i),
                    "category": "warning",
                })
        if "subprocess.run" in line and "timeout" not in line:
            findings.append({
                "file": rel,
                "line": i,
                "match": "subprocess.run sin timeout",
                "snippet": _snippet(lines, i),
                "category": "warning",
            })
    # except Exception as e seguido en pocas líneas de return Response 400/200
    for i, line in enumerate(lines):
        if not re.search(r"except\s+(Exception|\w+Exception)\s+as\s+\w+\s*:", line):
            continue
        for j in range(i + 1, min(i + 15, len(lines))):
            next_line = lines[j]
            if "return" in next_line and ("Response" in next_line or "HTMLResponse" in next_line) and ("400" in next_line or "200" in next_line):
                findings.append({
                    "file": rel,
                    "line": i + 1,
                    "match": "except Exception + return Response (400/200) en bloque",
                    "snippet": _snippet(lines, i + 1),
                    "category": "critical",
                })
                break
    return findings


def _snippet(lines: list[str], line_num: int, context: int = 1) -> str:
    lo = max(0, line_num - 1 - context)
    hi = min(len(lines), line_num - 1 + context + 1)
    return "\n".join(lines[lo:hi]).strip()[: 200]


# ----- Frontend: fetch sin helper -----

def check_js_or_html_fetch(path: Path, rel: str, lines: list[str]) -> list[dict]:
    """fetch( sin portalFetchWithTimeout en ~30 líneas."""
    findings = []
    if rel.replace("\\", "/") == HELPER_DEFINITION_FILE:
        return findings  # ui.js define el helper
    for i, line in enumerate(lines, 1):
        if "fetch(" not in line or "portalFetchWithTimeout" in line:
            continue
        # Buscar en ventana de 30 líneas si aparece portalFetchWithTimeout
        lo = max(0, i - 1 - 30)
        hi = min(len(lines), i - 1 + 31)
        window_text = "\n".join(lines[lo:hi])
        if "portalFetchWithTimeout" in window_text:
            continue  # OK, usa helper
        findings.append({
            "file": rel,
            "line": i,
            "match": "fetch( sin portalFetchWithTimeout en contexto",
            "snippet": _snippet(lines, i),
            "category": "warning",
        })
    return findings


def check_frontend_innerhtml(lines: list[str], rel: str) -> list[dict]:
    """innerHTML = con mensaje de error sin sanitizar (opcional warning)."""
    findings = []
    for i, line in enumerate(lines, 1):
        if "innerHTML" not in line or "=" not in line:
            continue
        if "error" in line.lower() or "message" in line.lower() or "detail" in line.lower():
            if "escape" not in line and "sanitize" not in line and "textContent" not in line:
                findings.append({
                    "file": rel,
                    "line": i,
                    "match": "innerHTML con posible mensaje de error (revisar sanitización)",
                    "snippet": _snippet(lines, i),
                    "category": "warning",
                })
    return findings


def run_audit(root: Path) -> tuple[list[dict], list[dict]]:
    backend_findings = []
    frontend_findings = []
    files = collect_files(root)
    for path, rel in files:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        lines = raw.splitlines()
        ext = path.suffix.lower()
        if ext == ".py":
            backend_findings.extend(check_python_file(path, rel, lines))
        if ext in (".js", ".html"):
            frontend_findings.extend(check_js_or_html_fetch(path, rel, lines))
            frontend_findings.extend(check_frontend_innerhtml(lines, rel))
    return backend_findings, frontend_findings


def write_report(out_path: Path, backend: list[dict], frontend: list[dict]) -> None:
    def table_rows(items: list[dict], cols: list[str]) -> list[str]:
        out = []
        for r in items:
            cells = [str(r.get(c, ""))[: 80] for c in cols]
            out.append("| " + " | ".join(cells) + " |")
        return out

    critical_back = [f for f in backend if f.get("category") == "critical"]
    warning_back = [f for f in backend if f.get("category") == "warning"]
    critical_front = [f for f in frontend if f.get("category") == "critical"]
    warning_front = [f for f in frontend if f.get("category") == "warning"]

    lines = [
        "# Reporte de cobertura de auditoría (estabilidad)",
        "",
        "Generado por `scripts/audit_coverage.py`. Revisar patrones que pueden indicar rezagos de Jobs 1-9.",
        "",
        "## 1. Resumen",
        "",
        "| Categoría | Backend (crítico) | Backend (warning) | Frontend (crítico) | Frontend (warning) |",
        "|-----------|-------------------|-------------------|--------------------|--------------------|",
        f"| # issues  | {len(critical_back)} | {len(warning_back)} | {len(critical_front)} | {len(warning_front)} |",
        "",
        "## 2. Backend findings",
        "",
    ]
    if not backend:
        lines.append("No se encontraron coincidencias.")
    else:
        lines.append("| Archivo | Línea | Match | Extracto |")
        lines.append("|---------|-------|-------|----------|")
        for r in backend:
            snippet = (r.get("snippet") or "").replace("|", "\\|").replace("\n", " ").strip()[: 80]
            lines.append(f"| {r['file']} | {r['line']} | {r['match']} | {snippet} |")
    lines.extend(["", "## 3. Frontend findings", ""])
    if not frontend:
        lines.append("No se encontraron coincidencias.")
    else:
        lines.append("| Archivo | Línea | Match | Extracto |")
        lines.append("|---------|-------|-------|----------|")
        for r in frontend:
            snippet = (r.get("snippet") or "").replace("|", "\\|").replace("\n", " ").strip()[: 80]
            lines.append(f"| {r['file']} | {r['line']} | {r['match']} | {snippet} |")
    lines.extend([
        "",
        "## 4. Recomendaciones",
        "",
        "1. **Backend 400/500:** Sustituir `return HTMLResponse(str(e), status_code=400)` por `logging.exception(...)` + `raise HTTPException(500, detail='Ocurrió un error. Intenta de nuevo.')` o dejar subir al handler 500.",
        "2. **Backend HTTPException(400):** No usar `detail=str(e)`; usar mensaje fijo para el usuario.",
        "3. **Frontend fetch:** Usar `portalFetchWithTimeout` (o `portalFetchJSON`) en lugar de `fetch()` directo para timeout, 401 y mensajes unificados.",
        "4. **logging.exception:** Tras registrar, relanzar con `raise` o `raise HTTPException(500, ...)` para no ocultar el error.",
        "5. **subprocess.run:** Añadir `timeout=N` para evitar bloqueos.",
        "",
    ])
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit coverage: genera AUDIT_COVERAGE_REPORT.md")
    parser.add_argument("--fail-on-issues", action="store_true", help="Exit 1 si hay findings críticos (backend)")
    parser.add_argument("--output", "-o", default="AUDIT_COVERAGE_REPORT.md", help="Ruta del reporte MD")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    out_path = root / args.output
    backend, frontend = run_audit(root)
    write_report(out_path, backend, frontend)
    critical_back = [f for f in backend if f.get("category") == "critical"]
    if args.fail_on_issues and critical_back:
        print(f"Audit: {len(critical_back)} critical backend issue(s). See {out_path}", file=sys.stderr)
        return 1
    print(f"Report written to {out_path} (backend: {len(backend)}, frontend: {len(frontend)} issues)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
