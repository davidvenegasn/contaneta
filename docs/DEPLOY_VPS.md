# Deploy ContaNeta on Ubuntu VPS

Complete guide to deploy ContaNeta on a fresh Ubuntu 22.04/24.04 VPS with Caddy (auto-HTTPS).

## Prerequisites

- A fresh Ubuntu 22.04+ VPS (e.g. DigitalOcean, Hetzner, Vultr)
- A domain pointing to the VPS IP (A record)
- SSH access as root

## Quick Start (1-Click)

```bash
# 1. SSH into your VPS
ssh root@YOUR_IP

# 2. Get the code
git clone YOUR_REPO_URL /opt/contaneta

# 3. Run the bootstrap (installs everything)
sudo bash /opt/contaneta/deploy/bootstrap_ubuntu.sh

# 4. Edit .env with real values
sudo nano /var/lib/contaneta/.env

# 5. Set up Caddy for HTTPS
sudo cp /opt/contaneta/deploy/caddy/Caddyfile /etc/caddy/Caddyfile
sudo sed -i 's/TU_DOMINIO.com/YOUR_DOMAIN.com/g' /etc/caddy/Caddyfile
sudo systemctl restart caddy

# 6. Start services
sudo systemctl enable --now contaneta-web
sudo systemctl enable --now contaneta-sat-worker
sudo systemctl enable --now contaneta-sat-scheduler.timer
sudo systemctl enable --now contaneta-backup.timer

# 7. Verify
curl https://YOUR_DOMAIN.com/health
```

## Step by Step

### 1. Create VPS + Point DNS

1. Create an Ubuntu 22.04 VPS (2GB RAM minimum recommended)
2. Note the IP address
3. In your DNS provider, create an A record: `YOUR_DOMAIN.com → VPS_IP`
4. Wait for DNS propagation (check with `dig YOUR_DOMAIN.com`)

### 2. Get the Code on the Server

```bash
ssh root@YOUR_IP
git clone YOUR_REPO_URL /opt/contaneta
```

Or use the deploy zip:
```bash
scp contaneta_deploy.zip root@YOUR_IP:/tmp/
ssh root@YOUR_IP
unzip /tmp/contaneta_deploy.zip -d /opt/contaneta
```

### 3. Run Bootstrap

```bash
sudo bash /opt/contaneta/deploy/bootstrap_ubuntu.sh
```

This idempotent script:
- Installs system packages (python3, php, sqlite3, Caddy, git, ufw)
- Creates `contaneta` system user
- Creates directories: `/opt/contaneta`, `/var/lib/contaneta`, `/var/log/contaneta`, `/var/backups/contaneta`
- Sets up Python virtualenv + installs dependencies
- Creates `.env` template at `/var/lib/contaneta/.env`
- Installs systemd services and timers
- Configures logrotate
- Opens firewall ports (22, 80, 443)

### 4. Configure Environment

```bash
sudo -u contaneta nano /var/lib/contaneta/.env
```

**Required values** — replace placeholders:

```bash
ENV=prod
SESSION_SECRET=<python3 -c "import secrets; print(secrets.token_hex(32))">
AT_REST_MASTER_KEY=<python3 -c "import secrets; print(secrets.token_hex(32))">
SITE_URL=https://YOUR_DOMAIN.com
APP_DB_PATH=/var/lib/contaneta/invoicing.db
APP_STORAGE_PATH=/var/lib/contaneta/storage
```

See `deploy/.env.example.prod` for the full template.

### 5. Set Up Caddy (HTTPS)

```bash
# Copy Caddyfile
sudo cp /opt/contaneta/deploy/caddy/Caddyfile /etc/caddy/Caddyfile

# Replace domain placeholder
sudo sed -i 's/TU_DOMINIO.com/YOUR_DOMAIN.com/g' /etc/caddy/Caddyfile

# Optional: set Let's Encrypt email
# sudo nano /etc/caddy/Caddyfile   # add: tls YOUR_EMAIL@example.com

# Start Caddy
sudo systemctl enable --now caddy
```

Caddy automatically obtains and renews HTTPS certificates from Let's Encrypt.

**Alternative: Nginx + Certbot** — see `deploy/nginx/contaneta.conf`:
```bash
sudo cp /opt/contaneta/deploy/nginx/contaneta.conf /etc/nginx/sites-available/contaneta
sudo ln -sf /etc/nginx/sites-available/contaneta /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d YOUR_DOMAIN.com
```

### 6. Start Services

```bash
sudo systemctl enable --now contaneta-web
sudo systemctl enable --now contaneta-sat-worker
sudo systemctl enable --now contaneta-sat-scheduler.timer
sudo systemctl enable --now contaneta-backup.timer
```

### 7. Verify

```bash
# Health check (direct)
curl -s http://localhost:8000/health | python3 -m json.tool

# Health check (via Caddy HTTPS)
curl -s https://YOUR_DOMAIN.com/health | python3 -m json.tool

# Check services
sudo systemctl status contaneta-web contaneta-sat-worker

# Check timers
sudo systemctl list-timers --all | grep contaneta

# Full smoke test
BASE_URL=https://YOUR_DOMAIN.com bash /opt/contaneta/scripts/smoke_prod.sh
```

Visit `/admin` in a browser to access the admin panel.

## Directory Layout

```
/opt/contaneta/                 # Application code (read-only in prod)
├── app.py                      # FastAPI application
├── deploy/                     # Deploy configs (systemd, Caddy, bootstrap)
├── scripts/                    # Ops scripts (backup, restore, triage)
├── .venv/                      # Python virtualenv
└── sat_sync/                   # PHP SAT sync scripts

/var/lib/contaneta/             # Application data
├── .env                        # Environment variables (chmod 600)
├── invoicing.db                # SQLite database
└── storage/                    # Uploaded files
    ├── xml_files/              # SAT CFDI XMLs
    ├── credentials/            # Encrypted FIEL .cer/.key (chmod 700)
    ├── uploads/                # Bank PDFs, month-close docs
    └── temp/                   # Temporary processing files

/var/log/contaneta/             # Application logs
├── web.log                     # App output
├── access.log                  # Gunicorn HTTP access
├── error.log                   # Gunicorn errors
├── worker.log                  # Job queue worker
├── sat_scheduler.log           # SAT scheduler
├── backup.log                  # Nightly backup
└── caddy_access.log            # Caddy access (if configured)

/var/backups/contaneta/         # Daily backups (7-day rotation)
├── invoicing_YYYYMMDD_HHMMSS.db.gz
└── storage_YYYYMMDD_HHMMSS.tar.gz
```

## Viewing Logs

```bash
# Web app (real-time)
sudo journalctl -u contaneta-web -f

# Or log file
tail -f /var/log/contaneta/web.log

# Worker
sudo journalctl -u contaneta-sat-worker -f

# Caddy access
tail -f /var/log/contaneta/caddy_access.log

# All ContaNeta services
sudo journalctl -u 'contaneta-*' --since "1 hour ago"
```

## Running Restore

```bash
# List available backups
ls -lt /var/backups/contaneta/invoicing_*.db.gz

# Restore latest
sudo bash /opt/contaneta/scripts/restore_latest.sh

# Restore specific backup
sudo bash /opt/contaneta/scripts/restore_latest.sh invoicing_20260303_020000.db.gz
```

## Running Diagnostics

```bash
sudo -u contaneta bash /opt/contaneta/scripts/ops_triage.sh
```

Shows: services status, DB health, recent errors, stuck jobs, disk usage, health check.

## Updating

```bash
cd /opt/contaneta
sudo -u contaneta git pull
sudo -u contaneta .venv/bin/pip install -q -r requirements.txt
sudo systemctl restart contaneta-web contaneta-sat-worker
# Migrations run automatically on app startup
```

## Troubleshooting

| Problem | Check |
|---------|-------|
| 502 Bad Gateway | `systemctl status contaneta-web` / `journalctl -u contaneta-web -n 50` |
| App won't start | Check `.env`: SESSION_SECRET set? DB path writable? |
| SAT sync not running | `systemctl status contaneta-sat-worker` / check `sat_jobs` table |
| Scheduler not enqueuing | `systemctl list-timers contaneta-sat-scheduler.timer` |
| SSL cert issue | Caddy auto-renews. Check: `caddy validate` / `systemctl status caddy` |
| DB locked | Only 1 gunicorn worker recommended (SQLite WAL). Check no stale processes |
| PHP errors | `php -v` and verify `sat_sync/vendor/` exists |

## Architecture Notes

- **1 gunicorn worker + 4 threads**: SQLite doesn't support concurrent writes. WAL mode + 1 writer is safest.
- **Worker** runs continuously (`--loop --sleep 2`), processing both `jobs` and `sat_jobs` queues.
- **Scheduler** runs every 10 minutes via systemd timer, enqueuing SAT sync for eligible issuers.
- **Backups** run daily at 3 AM — SQLite online backup + storage tar, 7-day rotation, optional S3 via rclone.
- **Caddy** handles HTTPS automatically via Let's Encrypt. No manual cert renewal needed.
- All services auto-restart on failure (systemd `Restart=always`).
