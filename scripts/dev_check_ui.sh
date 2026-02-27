#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

TEMPL_BASE="$ROOT/templates/base_portal.html"
TEMPL_DIR="$ROOT/templates"
CSS_DIR="$ROOT/static/css"

echo "== UI checks =="

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

warn() {
  echo "WARN: $*" >&2
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Falta comando requerido: $1"
}

need_cmd grep
need_cmd head
need_cmd wc
need_cmd sed
need_cmd tr

[[ -f "$TEMPL_BASE" ]] || fail "No existe: $TEMPL_BASE"

line_of() {
  local needle="$1"
  local file="$2"
  local out
  out="$(grep -nF "$needle" "$file" | head -n 1 || true)"
  [[ -n "$out" ]] || echo ""
  [[ -n "$out" ]] && echo "${out%%:*}"
}

echo
echo "-- CSS crítico en base_portal.html --"
L_TOKENS="$(line_of '/static/css/portal_tokens.css' "$TEMPL_BASE")"
L_COMPONENTS="$(line_of '/static/css/components.css' "$TEMPL_BASE")"
L_PORTAL_COMPONENTS="$(line_of '/static/css/portal_components.css' "$TEMPL_BASE")"
L_SHELL="$(line_of '/static/css/portal_shell.css' "$TEMPL_BASE")"
L_UI_V2="$(line_of '/static/css/portal_ui_v2.css' "$TEMPL_BASE")"
L_RAIL="$(line_of '/static/css/portal_rail.css' "$TEMPL_BASE")"
L_PORTAL_CSS="$(line_of '/static/css/portal.css' "$TEMPL_BASE")"

[[ -n "$L_TOKENS" ]] || fail "base_portal NO incluye portal_tokens.css"
[[ -n "$L_COMPONENTS" ]] || fail "base_portal NO incluye components.css"
[[ -n "$L_PORTAL_COMPONENTS" ]] || fail "base_portal NO incluye portal_components.css"
[[ -n "$L_SHELL" ]] || fail "base_portal NO incluye portal_shell.css (modales y layout)"

echo "OK: portal_tokens.css (línea $L_TOKENS)"
echo "OK: components.css (línea $L_COMPONENTS)"
echo "OK: portal_components.css (línea $L_PORTAL_COMPONENTS)"
echo "OK: portal_shell.css (línea $L_SHELL)"

if [[ "$L_TOKENS" -gt "$L_COMPONENTS" ]] || [[ "$L_COMPONENTS" -gt "$L_PORTAL_COMPONENTS" ]] || [[ "$L_PORTAL_COMPONENTS" -gt "$L_SHELL" ]]; then
  warn "Orden sugerido: tokens -> components -> portal_components -> portal_shell (revisa base_portal.html)"
fi

if [[ -n "$L_UI_V2" ]]; then echo "OK: portal_ui_v2.css (línea $L_UI_V2)"; else warn "No veo portal_ui_v2.css"; fi
if [[ -n "$L_RAIL" ]]; then echo "OK: portal_rail.css (línea $L_RAIL)"; else warn "No veo portal_rail.css"; fi
if [[ -n "$L_PORTAL_CSS" ]]; then echo "OK: portal.css (línea $L_PORTAL_CSS)"; else warn "No veo portal.css"; fi

echo
echo "-- Duplicados / imports peligrosos --"
if grep -R -n '@import "portal_shell.css"' "$CSS_DIR" >/dev/null 2>&1; then
  warn "Encontré @import \"portal_shell.css\" en CSS. Esto suele duplicar o desordenar el cascade."
  grep -R -n '@import "portal_shell.css"' "$CSS_DIR" || true
else
  echo "OK: no hay @import \"portal_shell.css\""
fi

echo
echo "-- Uso de .modal en templates --"
MODAL_COUNT="$(grep -R -n 'class="[^"]*modal' "$TEMPL_DIR" 2>/dev/null | wc -l | tr -d ' ')"
echo "Encontrados: $MODAL_COUNT ocurrencias (class contiene 'modal')"

echo
echo "-- Inline <style> en templates (warning) --"
STYLE_FILES="$(grep -R -n '<style>' "$TEMPL_DIR" 2>/dev/null || true)"
STYLE_COUNT="$(printf "%s" "$STYLE_FILES" | sed '/^$/d' | wc -l | tr -d ' ')"
if [[ "$STYLE_COUNT" -gt 0 ]]; then
  warn "Hay $STYLE_COUNT bloque(s) <style> inline en templates. Preferible mover a CSS global."
  echo "$STYLE_FILES" | head -n 30
else
  echo "OK: no hay <style> inline en templates"
fi

echo
echo "-- Guardrail: wrappers con 100vw (warning) --"
VW_FILES="$(grep -R -n '100vw' "$TEMPL_DIR" "$CSS_DIR" 2>/dev/null || true)"
VW_COUNT="$(printf "%s" "$VW_FILES" | sed '/^$/d' | wc -l | tr -d ' ')"
if [[ "$VW_COUNT" -gt 0 ]]; then
  warn "Encontré $VW_COUNT ocurrencia(s) de 100vw. Esto suele causar overflow horizontal o gaps raros."
  echo "$VW_FILES" | head -n 30
else
  echo "OK: no hay 100vw"
fi

echo
echo "== OK (sin fallas críticas) =="
