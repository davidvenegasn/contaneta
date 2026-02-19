
#!/bin/zsh
set -euo pipefail

# === Config ===
BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SAT_SYNC_DIR="$BASE_DIR/sat_sync"
DB_PATH="$BASE_DIR/invoicing.db"

PHP_BIN="/opt/homebrew/bin/php"
SQLITE_BIN="/usr/bin/sqlite3"
DATE_BIN="/bin/date"

# issuer_id=1 (cambia si luego manejas varios)
ISSUER_ID="1"

# Backfill (solo se usa si NO hay checkpoint previo)
BACKFILL_DAYS="90"
WINDOW_HOURS="72"

# Si vamos atrasados más de ~1 ventana, entramos en modo backfill-loop
LAG_THRESHOLD_SECONDS=$((WINDOW_HOURS * 3600))

# Seguridad: límite de loops por ejecución del job (para no colgar launchd)
MAX_LOOPS="120"
SLEEP_BETWEEN_LOOPS_SECONDS="10"

cd "$SAT_SYNC_DIR"

get_last_sync_to() {
  local direction="$1"
  "$SQLITE_BIN" "$DB_PATH" "SELECT last_sync_to FROM sat_sync_state WHERE issuer_id=$ISSUER_ID AND direction='${direction}' LIMIT 1;" 2>/dev/null || true
}

to_epoch() {
  local ts="$1"
  # Espera formato: YYYY-MM-DD HH:MM:SS
  if [[ -z "$ts" ]]; then
    echo ""
    return 0
  fi
  "$DATE_BIN" -j -f "%Y-%m-%d %H:%M:%S" "$ts" "+%s" 2>/dev/null || echo ""
}

now_epoch() {
  "$DATE_BIN" "+%s"
}

compute_lag_seconds() {
  local direction="$1"
  local last_ts
  local last_epoch
  local now

  last_ts="$(get_last_sync_to "$direction")"
  last_epoch="$(to_epoch "$last_ts")"
  now="$(now_epoch)"

  if [[ -z "$last_epoch" ]]; then
    # Sin checkpoint -> tratamos como muy atrasado
    echo "999999999"
    return 0
  fi

  # lag = ahora - last_sync_to
  echo $((now - last_epoch))
}

run_once() {
  local mode="$1"  # normal|backfill_first|backfill_loop

  echo "[run_sync] mode=$mode issuer_id=$ISSUER_ID window=${WINDOW_HOURS}h" 1>&1

  if [[ "$mode" == "backfill_first" ]]; then
    "$PHP_BIN" sync.php "$ISSUER_ID" issued --backfill="$BACKFILL_DAYS" --reset --window="$WINDOW_HOURS"
    "$PHP_BIN" sync.php "$ISSUER_ID" received --backfill="$BACKFILL_DAYS" --reset --window="$WINDOW_HOURS"
  else
    # normal / backfill_loop: NO usamos --reset para no perder el checkpoint
    "$PHP_BIN" sync.php "$ISSUER_ID" issued --backfill="$BACKFILL_DAYS" --window="$WINDOW_HOURS"
    "$PHP_BIN" sync.php "$ISSUER_ID" received --backfill="$BACKFILL_DAYS" --window="$WINDOW_HOURS"
  fi
}

# === Decide modo ===
lag_issued="$(compute_lag_seconds issued)"
lag_received="$(compute_lag_seconds received)"

# Si no hay checkpoint previo en alguno, hacemos 1 corrida con --reset para inicializar
if [[ "$lag_issued" == "999999999" || "$lag_received" == "999999999" ]]; then
  run_once "backfill_first"
  exit 0
fi

# Si estamos atrasados más que el umbral, hacemos loop en esta ejecución
if (( lag_issued > LAG_THRESHOLD_SECONDS || lag_received > LAG_THRESHOLD_SECONDS )); then
  echo "[run_sync] atrasado: issued=${lag_issued}s received=${lag_received}s -> backfill loop" 1>&1

  loops=0
  while (( loops < MAX_LOOPS )); do
    loops=$((loops + 1))
    echo "[run_sync] loop ${loops}/${MAX_LOOPS}" 1>&1

    run_once "backfill_loop"

    # Recalcular lag
    lag_issued="$(compute_lag_seconds issued)"
    lag_received="$(compute_lag_seconds received)"
    echo "[run_sync] lag: issued=${lag_issued}s received=${lag_received}s" 1>&1

    # Si ya estamos al corriente (<= umbral), salimos
    if (( lag_issued <= LAG_THRESHOLD_SECONDS && lag_received <= LAG_THRESHOLD_SECONDS )); then
      echo "[run_sync] al corriente. fin." 1>&1
      exit 0
    fi

    sleep "$SLEEP_BETWEEN_LOOPS_SECONDS"
  done

  echo "[run_sync] se alcanzó MAX_LOOPS=${MAX_LOOPS}. se deja para la siguiente ejecución." 1>&1
  exit 0
fi

# Si no estamos atrasados, corrida normal
run_once "normal"
exit 0
