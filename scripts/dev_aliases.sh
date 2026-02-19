# Aliases útiles para desarrollo.
# Cargar con: source scripts/dev_aliases.sh  (desde cualquier carpeta, en bash o zsh)
# O copiar a ~/.bashrc o ~/.zshrc para uso permanente.

# Ruta del script al ser sourceado: en bash $0 no es fiable; en zsh tampoco.
# bash: BASH_SOURCE[0]; zsh: %x (path del archivo actual siendo ejecutado)
if [ -n "$ZSH_VERSION" ]; then
  _DEV_ALIASES_SCRIPT="${(%):-%x}"
else
  _DEV_ALIASES_SCRIPT="${BASH_SOURCE[0]}"
fi

SCRIPT_DIR="$(cd "$(dirname "$_DEV_ALIASES_SCRIPT")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Aliases que usan PROJECT_ROOT (funcionan desde cualquier directorio actual)
alias migrate='python3 "$PROJECT_ROOT/scripts/run_migrations.py"'
alias checkdb='python3 "$PROJECT_ROOT/scripts/check_db.py"'
alias run='cd "$PROJECT_ROOT" && uvicorn app:app --reload'

echo "Aliases cargados (PROJECT_ROOT=$PROJECT_ROOT):"
echo "  migrate  - Ejecutar migraciones manualmente"
echo "  checkdb  - Verificar estado de la DB"
echo "  run      - Arrancar servidor de desarrollo"
