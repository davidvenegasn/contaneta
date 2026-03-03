#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# ContaNeta Production Bootstrap
#
# Run as root (or with sudo) on a fresh Ubuntu 22.04/24.04 VPS.
# Creates user, directories, installs dependencies, sets up venv.
#
# Usage:
#   sudo bash scripts/prod_bootstrap.sh
# ──────────────────────────────────────────────────────────────
set -euo pipefail

APP_USER="${APP_USER:-contaneta}"
APP_DIR="/opt/contaneta"
DATA_DIR="/var/lib/contaneta"
LOG_DIR="/var/log/contaneta"
BACKUP_DIR="/var/backups/contaneta"

echo "=== ContaNeta Production Bootstrap ==="
echo "  App dir:    $APP_DIR"
echo "  Data dir:   $DATA_DIR"
echo "  Log dir:    $LOG_DIR"
echo "  Backup dir: $BACKUP_DIR"
echo "  User:       $APP_USER"
echo

# ── 1. System packages ───────────────────────────────────────
echo "--- Installing system packages ---"
apt-get update -qq
apt-get install -y -qq \
    python3 python3-pip python3-venv \
    php-cli php-curl php-xml php-mbstring php-sqlite3 \
    sqlite3 \
    git \
    ufw \
    logrotate

# ── 2. Create app user ───────────────────────────────────────
echo "--- Creating user: $APP_USER ---"
if ! id "$APP_USER" &>/dev/null; then
    useradd -r -m -s /bin/bash "$APP_USER"
    echo "  Created system user: $APP_USER"
else
    echo "  User $APP_USER already exists"
fi

# ── 3. Create directories ────────────────────────────────────
echo "--- Creating directories ---"
mkdir -p "$APP_DIR"
mkdir -p "$DATA_DIR/storage/xml_files"
mkdir -p "$DATA_DIR/storage/credentials"
mkdir -p "$DATA_DIR/storage/temp"
mkdir -p "$LOG_DIR"
mkdir -p "$BACKUP_DIR"

chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chown -R "$APP_USER:$APP_USER" "$DATA_DIR"
chown -R "$APP_USER:$APP_USER" "$LOG_DIR"
chown -R "$APP_USER:$APP_USER" "$BACKUP_DIR"

# Storage credentials: restricted permissions
chmod 700 "$DATA_DIR/storage/credentials"

echo "  $APP_DIR (code)"
echo "  $DATA_DIR (db + storage)"
echo "  $LOG_DIR (logs)"
echo "  $BACKUP_DIR (backups)"

# ── 4. Clone/update code ─────────────────────────────────────
if [ ! -d "$APP_DIR/.git" ]; then
    echo "--- Repository not found. Clone manually: ---"
    echo "  sudo -u $APP_USER git clone YOUR_REPO_URL $APP_DIR"
    echo
else
    echo "--- Repository exists at $APP_DIR ---"
fi

# ── 5. Python virtualenv ─────────────────────────────────────
echo "--- Setting up Python virtualenv ---"
if [ ! -d "$APP_DIR/.venv" ]; then
    sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
    echo "  Created .venv"
fi
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
if [ -f "$APP_DIR/requirements.txt" ]; then
    sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
    echo "  Dependencies installed"
fi

# ── 6. .env file ─────────────────────────────────────────────
if [ ! -f "$APP_DIR/.env" ]; then
    echo "--- Creating .env from template ---"
    if [ -f "$APP_DIR/.env.example" ]; then
        cp "$APP_DIR/.env.example" "$APP_DIR/.env"
        chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
        chmod 600 "$APP_DIR/.env"
        echo "  Created .env from .env.example — EDIT IT NOW:"
        echo "    sudo -u $APP_USER nano $APP_DIR/.env"
    else
        echo "  WARNING: .env.example not found"
    fi
else
    echo "--- .env already exists ---"
fi
# Ensure restrictive permissions
chmod 600 "$APP_DIR/.env" 2>/dev/null || true

# ── 7. Suggested .env values for prod ────────────────────────
echo
echo "=== IMPORTANT: Edit .env with these production values ==="
echo "  ENV=prod"
echo "  DEV_MODE=0"
echo "  ALLOW_DEMO_PORTAL=0"
echo "  SESSION_SECRET=$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
echo "  AT_REST_MASTER_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
echo "  APP_DB_PATH=$DATA_DIR/invoicing.db"
echo "  APP_STORAGE_PATH=$DATA_DIR/storage"
echo "  BACKUP_DIR=$BACKUP_DIR"
echo "  COOKIE_SECURE=1"
echo "  SITE_URL=https://TU_DOMINIO.com"
echo "  ADMIN_PASSWORD=<strong-password>"
echo

# ── 8. Run migrations ────────────────────────────────────────
if [ -f "$APP_DIR/.env" ] && [ -f "$APP_DIR/migrations_runner.py" ]; then
    echo "--- Running migrations ---"
    DB_PATH=$(grep -E "^APP_DB_PATH=" "$APP_DIR/.env" 2>/dev/null | cut -d= -f2 || echo "$DATA_DIR/invoicing.db")
    if [ -n "$DB_PATH" ]; then
        sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" -c "
from migrations_runner import apply_migrations
apply_migrations('$DB_PATH')
print('Migrations applied successfully')
" 2>&1 || echo "  WARNING: Migration failed (configure .env first)"
    fi
fi

# ── 9. Install systemd services ──────────────────────────────
echo "--- Installing systemd services ---"
for svc in contaneta-web contaneta-sat-worker contaneta-sat-scheduler contaneta-backup; do
    src="$APP_DIR/deploy/systemd/${svc}.service"
    if [ -f "$src" ]; then
        cp "$src" /etc/systemd/system/
        echo "  Installed ${svc}.service"
    fi
done
for timer in contaneta-sat-scheduler contaneta-backup; do
    src="$APP_DIR/deploy/systemd/${timer}.timer"
    if [ -f "$src" ]; then
        cp "$src" /etc/systemd/system/
        echo "  Installed ${timer}.timer"
    fi
done
systemctl daemon-reload
echo "  systemctl daemon-reload done"

# ── 10. Logrotate ────────────────────────────────────────────
echo "--- Installing logrotate config ---"
cat > /etc/logrotate.d/contaneta << 'LOGROTATE'
/var/log/contaneta/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 contaneta contaneta
    sharedscripts
    postrotate
        systemctl reload contaneta-web 2>/dev/null || true
    endscript
}
LOGROTATE
echo "  Installed /etc/logrotate.d/contaneta"

# ── 11. Firewall ─────────────────────────────────────────────
echo "--- Firewall (ufw) ---"
ufw allow 22/tcp   >/dev/null 2>&1 || true
ufw allow 80/tcp   >/dev/null 2>&1 || true
ufw allow 443/tcp  >/dev/null 2>&1 || true
echo "  Allowed: 22, 80, 443"
echo "  Enable with: sudo ufw enable"

echo
echo "=== Bootstrap complete ==="
echo
echo "Next steps:"
echo "  1) Edit .env:        sudo -u $APP_USER nano $APP_DIR/.env"
echo "  2) Start services:   sudo systemctl enable --now contaneta-web contaneta-sat-worker"
echo "  3) Start timers:     sudo systemctl enable --now contaneta-sat-scheduler.timer contaneta-backup.timer"
echo "  4) Set up reverse proxy (Caddy recommended):"
echo "     - Install Caddy:  See deploy/caddy/Caddyfile for instructions"
echo "     - Copy config:    sudo cp $APP_DIR/deploy/caddy/Caddyfile /etc/caddy/Caddyfile"
echo "     - Edit domain:    sudo nano /etc/caddy/Caddyfile"
echo "     - Start:          sudo systemctl enable --now caddy"
echo "  5) Verify:           curl http://localhost:8000/health"
echo "  6) Smoke test:       cd $APP_DIR && bash scripts/smoke_release.sh"
