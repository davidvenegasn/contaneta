#!/usr/bin/env python3
"""
Auditoría: detecta subprocess.run() o subprocess.Popen() sin timeout en el código.
Si encuentra alguno, imprime la ruta y línea y sale con código 1.
Excluye: tests, scripts/legacy, services/subprocess_safe.py, y líneas que contienen "timeout".
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXCLUDE_DIRS = {"legacy", ".git", "__pycache__", "venv", ".venv", "node_modules"}
EXCLUDE_FILES = {"subprocess_safe.py"}

# subprocess.run( ... ) sin timeout= en la misma llamada (simplificado: busca run( y luego en las ~15 líneas siguientes si hay timeout=)
RUN_PATTERN = re.compile(r"subprocess\.run\s*\(")
POPEN_PATTERN = re.compile(r"subprocess\.Popen\s*\(")
TIMEOUT_PATTERN = re.compile(r"timeout\s*=")


def check_file(path: str) -> list[tuple[int, str]]:
    issues = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    for i, line in enumerate(lines, 1):
        if RUN_PATTERN.search(line) or POPEN_PATTERN.search(line):
            # Buscar en esta línea y las siguientes 12 si hay timeout=
            block = " ".join(lines[i - 1 : min(i + 12, len(lines))])
            if not TIMEOUT_PATTERN.search(block):
                issues.append((i, line.strip()[:80]))
    return issues


def main():
    found = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        if "test" in dirpath.split(os.sep) or "legacy" in dirpath.split(os.sep):
            continue
        for f in filenames:
            if not f.endswith(".py"):
                continue
            if f in EXCLUDE_FILES:
                continue
            path = os.path.join(dirpath, f)
            rel = os.path.relpath(path, ROOT)
            issues = check_file(path)
            for line_no, content in issues:
                found.append((rel, line_no, content))
    if found:
        for rel, line_no, content in found:
            print(f"{rel}:{line_no}: {content}")
        print(f"\nTotal: {len(found)} llamada(s) a subprocess sin timeout detectada(s).")
        sys.exit(1)
    print("OK: no se encontraron subprocess.run/Popen sin timeout.")
    sys.exit(0)


if __name__ == "__main__":
    main()
