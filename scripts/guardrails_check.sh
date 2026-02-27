#!/usr/bin/env bash
set -euo pipefail

echo "[guardrails] Running checks..."

# 1) No tocar snapshot: falla si algún archivo modificado o en el último commit está bajo _snapshot_before_mindtrip
CHANGED="$(git diff --name-only 2>/dev/null || true)"
CHANGED_CACHED="$(git diff --name-only --cached 2>/dev/null || true)"
if [ -n "$CHANGED" ] || [ -n "$CHANGED_CACHED" ]; then
  if echo "$CHANGED $CHANGED_CACHED" | tr ' ' '\n' | grep -q "^_snapshot_before_mindtrip"; then
    echo "ERROR: Se modificó algo bajo _snapshot_before_mindtrip. Revertir ese cambio (ver docs/GUARDRAILS.md)."
    exit 1
  fi
fi
# También revisar último commit si existe
if git rev-parse HEAD~1 >/dev/null 2>&1; then
  if git diff --name-only HEAD~1..HEAD | grep -q "^_snapshot_before_mindtrip"; then
    echo "ERROR: El último commit modificó _snapshot_before_mindtrip. Revertir ese cambio."
    exit 1
  fi
fi

# 2) base_portal.html debe contener block content
if ! grep -q "{% block content %}" templates/base_portal.html 2>/dev/null; then
  echo "ERROR: templates/base_portal.html perdió '{% block content %}'."
  exit 1
fi
if ! grep -q "{% endblock %}" templates/base_portal.html 2>/dev/null; then
  echo "ERROR: templates/base_portal.html parece incompleto (falta endblock)."
  exit 1
fi

echo "[guardrails] OK"
