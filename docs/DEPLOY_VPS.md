# Deploy ContaNeta on Ubuntu VPS

Complete guide to deploy ContaNeta on a fresh Ubuntu 22.04/24.04 VPS.

## 1. Server Setup

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install dependencies
sudo apt install -y \
    nginx \
    python3 python3-pip python3-venv \
    php-cli php-curl php-xml php-mbstring php-sqlite3 \
    sqlite3 \
    certbot python3-certbot-nginx \
    git \
    ufw

# Create deploy user
sudo useradd -m -s /bin/bash deploy
sudo mkdir -p /opt/contaneta
sudo chown deploy:deploy /opt/contaneta
```

## 2. Application Setup

```bash
# Switch to deploy user
sudo -u deploy -i

# Clone repository
cd /opt/contaneta
git clone YOUR_REPO_URL .

# Python virtualenv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Create directories
mkdir -p logs storage/xml_files storage/credentials backups

# Environment configuration
cp .env.example .env
nano .env   # Edit with your values (see section below)
```

## 3. Environment Variables (.env)

```bash
# Required in production
ENV=prod
SESSION_SECRET=<generate with: python3 -c "import secrets; print(secrets.token_hex(32))">
AT_REST_MASTER_KEY=<generate with: python3 -c "import secrets; print(secrets.token_hex(32))">
APP_DB_PATH=/opt/contaneta/invoicing.db
SITE_URL=https://TU_DOMINIO.com

# Admin
ADMIN_PASSWORD=<strong password for /admin basic auth>

# Stripe (billing)
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID=price_...

# SAT sync
PHP_BIN=php
SAT_SYNC_BACKFILL_DAYS=7
SAT_SYNC_WINDOW_HOURS=6

# Optional: Sentry
# SENTRY_DSN=https://xxx@sentry.io/yyy

# Optional: Backups to S3
# BACKUP_RCLONE_REMOTE=contaneta-backup:bucket/path
```

## 4. Run Migrations

```bash
cd /opt/contaneta
source .venv/bin/activate
python -c "from migrations_runner import apply_migrations; apply_migrations('/opt/contaneta/invoicing.db')"
```

## 5. PHP Dependencies (SAT sync)

```bash
cd /opt/contaneta/sat_sync
# Install Composer if not present
php -r "copy('https://getcomposer.org/installer', 'composer-setup.php');"
php composer-setup.php
php -r "unlink('composer-setup.php');"
php composer.phar install --no-dev
```

## 6. Systemd Services

```bash
# Copy service files
sudo cp deploy/systemd/contaneta-web.service /etc/systemd/system/
sudo cp deploy/systemd/contaneta-sat-worker.service /etc/systemd/system/
sudo cp deploy/systemd/contaneta-sat-scheduler.service /etc/systemd/system/
sudo cp deploy/systemd/contaneta-sat-scheduler.timer /etc/systemd/system/
sudo cp deploy/systemd/contaneta-backup.service /etc/systemd/system/
sudo cp deploy/systemd/contaneta-backup.timer /etc/systemd/system/

# Reload and enable
sudo systemctl daemon-reload
sudo systemctl enable contaneta-web contaneta-sat-worker
sudo systemctl enable contaneta-sat-scheduler.timer contaneta-backup.timer

# Start services
sudo systemctl start contaneta-web
sudo systemctl start contaneta-sat-worker
sudo systemctl start contaneta-sat-scheduler.timer
sudo systemctl start contaneta-backup.timer

# Verify
sudo systemctl status contaneta-web
sudo systemctl status contaneta-sat-worker
sudo systemctl list-timers --all | grep contaneta
```

## 7. Nginx + SSL

```bash
# Copy nginx config
sudo cp deploy/nginx/contaneta.conf /etc/nginx/sites-available/contaneta.conf

# Edit: replace TU_DOMINIO.com with your actual domain
sudo nano /etc/nginx/sites-available/contaneta.conf

# Enable site
sudo ln -sf /etc/nginx/sites-available/contaneta.conf /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default  # Remove default site

# Test and reload
sudo nginx -t
sudo systemctl reload nginx

# SSL with Let's Encrypt
sudo certbot --nginx -d TU_DOMINIO.com
# Follow prompts, choose redirect HTTP→HTTPS
```

## 8. Firewall

```bash
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP (for certbot renewal)
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable
sudo ufw status
```

## 9. Log Rotation

```bash
# Copy logrotate config
sudo cp deploy/logrotate-conta.example /etc/logrotate.d/contaneta

# Or create manually:
sudo tee /etc/logrotate.d/contaneta << 'LOGROTATE'
/opt/contaneta/logs/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 deploy deploy
    sharedscripts
    postrotate
        systemctl reload contaneta-web 2>/dev/null || true
    endscript
}
LOGROTATE
```

## 10. Verify Deployment

```bash
# Health check
curl -s http://localhost:8000/health

# From outside
curl -s https://TU_DOMINIO.com/health

# Check services
sudo systemctl status contaneta-web contaneta-sat-worker

# Check timers
sudo systemctl list-timers contaneta-*

# Check logs
tail -f /opt/contaneta/logs/web.log
tail -f /opt/contaneta/logs/worker.log

# Run smoke test
cd /opt/contaneta && bash scripts/smoke_release.sh
```

## Updates

```bash
# Pull latest code
sudo -u deploy -i
cd /opt/contaneta
git pull

# Update dependencies
source .venv/bin/activate
pip install -r requirements.txt

# Restart services (migrations run automatically on startup)
sudo systemctl restart contaneta-web contaneta-sat-worker
```

## Troubleshooting

| Problem | Check |
|---------|-------|
| 502 Bad Gateway | `sudo systemctl status contaneta-web` / `journalctl -u contaneta-web` |
| SAT sync not running | `sudo systemctl status contaneta-sat-worker` / check `sat_jobs` table |
| Scheduler not enqueuing | `sudo systemctl list-timers contaneta-sat-scheduler.timer` |
| SSL cert expired | `sudo certbot renew --dry-run` |
| DB locked | Check if multiple writers; SQLite uses WAL mode — only 1 gunicorn worker recommended |
| PHP errors | `php -v` and check `sat_sync/vendor/` exists |

## Architecture Notes

- **1 gunicorn worker** is recommended because SQLite doesn't support concurrent writes well. WAL mode helps but 1 writer is safest.
- The **worker** runs in loop mode, polling every 2 seconds for new jobs.
- The **scheduler** runs every 10 minutes via systemd timer, enqueuing eligible issuers.
- **Backups** run nightly at 3 AM with 7-day rotation.
- All services auto-restart on failure (systemd `Restart=always`).
