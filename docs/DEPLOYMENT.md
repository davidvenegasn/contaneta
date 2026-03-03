# Deployment Guide — ContaNeta

## Prerequisites

- Ubuntu 22.04+ or Debian 12+ (recommended)
- Python 3.11+
- PHP 8.1+ (for SAT sync)
- SQLite 3.35+ (WAL mode, `RETURNING` clause)
- Caddy or Nginx (reverse proxy + TLS)

---

## 1. Server Setup

### Create Application User

```bash
sudo useradd -r -m -d /var/www/conta-invoicing -s /bin/bash conta
```

### Install Dependencies

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip sqlite3 php-cli php-xml php-curl
```

### Deploy Code

```bash
# Option A: safe_export.sh (excludes secrets, DB, storage)
bash scripts/safe_export.sh
# Upload conta-export.tar.gz to server
scp conta-export.tar.gz server:/var/www/conta-invoicing/

# Option B: git clone (then remove unneeded files)
cd /var/www/conta-invoicing
git clone <repo-url> .
rm -rf tests/ scripts/*.py docs/ .claude/
```

### Python Environment

```bash
cd /var/www/conta-invoicing
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## 2. Configuration

### Create `.env`

```bash
cp .env.example .env
chmod 600 .env  # restrict permissions
```

### Mandatory Production Values

```bash
# Generate secrets
python3 -c "import secrets; print('SESSION_SECRET=' + secrets.token_hex(32))"
python3 -c "import secrets; print('AT_REST_MASTER_KEY=' + secrets.token_hex(32))"

# Set in .env:
ENV=prod
DEV_MODE=0
ALLOW_DEMO_PORTAL=0
SESSION_SECRET=<generated-64-char-hex>
COOKIE_SECURE=1
APP_DB_PATH=/var/www/conta-invoicing/invoicing.db
SITE_URL=https://your-domain.com
ADMIN_PASSWORD=<strong-password>
```

### Optional but Recommended

```bash
# Facturapi (invoicing)
FACTURAPI_SECRET_KEY=<your-key>

# SMTP (email verification + password reset)
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=noreply@your-domain.com
SMTP_PASSWORD=<smtp-password>
SMTP_FROM=noreply@your-domain.com

# Stripe (subscriptions)
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID=price_...

# OAuth (social login)
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...

# Encryption at rest (FIEL credentials)
AT_REST_MASTER_KEY=<generated-64-char-hex>

# Logging
LOG_FILE=/var/log/conta/app.log
```

---

## 3. Directory Structure

```bash
# Create required directories
mkdir -p storage/{xml,pdfs,credentials,bank,exports}
mkdir -p backup
mkdir -p /var/log/conta

# Set permissions
chown -R conta:conta /var/www/conta-invoicing
chmod 700 storage/credentials
```

---

## 4. Database Initialization

Migrations run automatically on first startup. To initialize manually:

```bash
source venv/bin/activate
python3 -c "from migrations_runner import apply_migrations; apply_migrations()"
```

Verify:
```bash
sqlite3 invoicing.db "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 5;"
```

---

## 5. Reverse Proxy

### Option A: Caddy (recommended — automatic TLS)

```bash
sudo cp deploy/Caddyfile.example /etc/caddy/Caddyfile
# Edit domain and paths
sudo systemctl reload caddy
```

### Option B: Nginx

```bash
sudo cp deploy/nginx-conta.example.conf /etc/nginx/sites-available/conta
sudo ln -s /etc/nginx/sites-available/conta /etc/nginx/sites-enabled/
# Edit domain, paths, SSL cert paths
sudo nginx -t && sudo systemctl reload nginx
```

---

## 6. Systemd Service

### Application Server

```bash
sudo cp deploy/conta-invoicing.service /etc/systemd/system/
# Edit paths and user in the service file
sudo systemctl daemon-reload
sudo systemctl enable conta-invoicing
sudo systemctl start conta-invoicing
```

Verify:
```bash
sudo systemctl status conta-invoicing
curl -s http://localhost:8000/health | python3 -m json.tool
```

### Worker (optional — for generic job queue)

```bash
cat > /etc/systemd/system/conta-worker.service << 'EOF'
[Unit]
Description=ContaNeta Job Worker
After=network.target

[Service]
Type=simple
User=conta
Group=conta
WorkingDirectory=/var/www/conta-invoicing
EnvironmentFile=-/var/www/conta-invoicing/.env
ExecStart=/var/www/conta-invoicing/venv/bin/python worker.py --loop --sleep 2.0
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable conta-worker
sudo systemctl start conta-worker
```

---

## 7. Cron Jobs

```bash
sudo -u conta crontab -e
```

Add:
```crontab
# SAT sync every 15 minutes
*/15 * * * * cd /var/www/conta-invoicing && ./sat_sync/cron_sat_sync.sh >> /var/log/conta/sat_sync.log 2>&1

# SAT job queue every 5 minutes
*/5 * * * * cd /var/www/conta-invoicing && venv/bin/python scripts/sat_worker.py >> /var/log/conta/sat_worker.log 2>&1

# Database backup daily at 2 AM
0 2 * * * cd /var/www/conta-invoicing && bash scripts/backup_db.sh >> /var/log/conta/backup.log 2>&1

# Storage backup weekly (Sunday 3 AM)
0 3 * * 0 cd /var/www/conta-invoicing && bash scripts/backup_storage.sh >> /var/log/conta/backup.log 2>&1
```

---

## 8. Log Rotation

```bash
sudo cp deploy/logrotate-conta.example /etc/logrotate.d/conta-invoicing
# Edit paths to match your installation
```

---

## 9. Stripe Webhook

If using Stripe billing:

```bash
# Register webhook endpoint
# URL: https://your-domain.com/webhooks/stripe
# Events: checkout.session.completed, customer.subscription.updated,
#          customer.subscription.deleted, invoice.payment_succeeded,
#          invoice.payment_failed

# Set the webhook signing secret in .env
STRIPE_WEBHOOK_SECRET=whsec_...
```

---

## 10. Post-Deploy Verification

```bash
# Health check
curl -sf https://your-domain.com/health | python3 -m json.tool

# Readiness (for load balancers)
curl -sf https://your-domain.com/ready

# Login page loads
curl -sf -o /dev/null -w "%{http_code}" https://your-domain.com/login
# Expected: 200

# API returns 401 without auth
curl -sf -o /dev/null -w "%{http_code}" https://your-domain.com/api/account/status
# Expected: 401

# Admin panel accessible
curl -sf -o /dev/null -w "%{http_code}" -u admin:$ADMIN_PASSWORD https://your-domain.com/admin/
# Expected: 200

# Run smoke tests
bash scripts/smoke_release.sh
```

---

## 11. Updating

```bash
# 1. Backup
sudo -u conta bash scripts/backup_db.sh

# 2. Deploy new code
cd /var/www/conta-invoicing
sudo -u conta git pull  # or upload new export

# 3. Update dependencies (if requirements.txt changed)
sudo -u conta venv/bin/pip install -r requirements.txt

# 4. Restart (migrations run automatically)
sudo systemctl restart conta-invoicing

# 5. Verify
curl -s https://your-domain.com/health | python3 -m json.tool
```

---

## 12. Security Checklist

- [ ] `ENV=prod` and `DEV_MODE=0`
- [ ] `SESSION_SECRET` is unique 64-char hex (not shared across environments)
- [ ] `COOKIE_SECURE=1` (HTTPS required)
- [ ] `ALLOW_DEMO_PORTAL=0`
- [ ] `.env` has `chmod 600` permissions
- [ ] `storage/credentials/` has `chmod 700` permissions
- [ ] Firewall: only ports 80/443 open
- [ ] HTTPS configured (Caddy auto-TLS or manual cert)
- [ ] `ADMIN_PASSWORD` is strong (20+ characters)
- [ ] `AT_REST_MASTER_KEY` set (separate from `SESSION_SECRET`)
- [ ] Backups configured and tested
- [ ] Log rotation configured
- [ ] No `print()` statements leaking secrets (already audited)

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| App won't start: "SESSION_SECRET required" | Set `SESSION_SECRET` in `.env` |
| App won't start: "SITE_URL required" | Set `SITE_URL=https://...` in `.env` |
| 502 Bad Gateway | Check `systemctl status conta-invoicing` and app logs |
| DB locked | Check for zombie processes: `lsof invoicing.db` |
| SAT sync failing | Check PHP is installed: `php --version`; check FIEL uploaded |
| Cookies not persisting | Ensure `COOKIE_SECURE=1` matches HTTPS; check SameSite |
| CSRF errors | Ensure `SITE_URL` matches actual domain |
| Stripe webhooks failing | Verify `STRIPE_WEBHOOK_SECRET` matches Stripe dashboard |
