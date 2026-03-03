# ContaNeta — Production Deployment

## Quick Start (Ubuntu 22.04/24.04)

```bash
# 1. Get the code on the server
git clone YOUR_REPO_URL /opt/contaneta

# 2. Run bootstrap (installs deps, Caddy, creates user/dirs/venv/systemd)
sudo bash /opt/contaneta/deploy/bootstrap_ubuntu.sh

# 3. Edit .env with real values
sudo nano /var/lib/contaneta/.env

# 4. Set up Caddy (HTTPS)
sudo cp /opt/contaneta/deploy/caddy/Caddyfile /etc/caddy/Caddyfile
sudo sed -i 's/TU_DOMINIO.com/YOUR_DOMAIN.com/g' /etc/caddy/Caddyfile
sudo systemctl enable --now caddy

# 5. Start services
sudo systemctl enable --now contaneta-web contaneta-sat-worker
sudo systemctl enable --now contaneta-sat-scheduler.timer contaneta-backup.timer

# 6. Verify
curl https://YOUR_DOMAIN.com/health
BASE_URL=https://YOUR_DOMAIN.com bash /opt/contaneta/scripts/smoke_prod.sh
```

## Directory Layout (production)

```
/opt/contaneta/            # Application code (git repo)
├── .env -> /var/lib/contaneta/.env  # Symlink to data dir
├── .venv/                 # Python virtualenv
├── deploy/                # Deployment configs
│   ├── systemd/           # systemd service + timer files
│   ├── caddy/             # Caddyfile
│   └── nginx/             # nginx config (alternative to Caddy)
├── scripts/               # Operational scripts
└── sat_sync/              # PHP SAT sync scripts + vendor/

/var/lib/contaneta/        # Persistent data (outside repo)
├── invoicing.db           # SQLite database
└── storage/
    ├── xml_files/         # SAT CFDI XML files
    ├── credentials/       # Encrypted FIEL files (chmod 700)
    └── temp/              # Temporary files

/var/log/contaneta/        # Logs (logrotated daily, 14 days)
├── web.log                # Gunicorn app log
├── access.log             # HTTP access log
├── worker.log             # Job worker log
├── sat_scheduler.log      # SAT scheduler log
└── backup.log             # Backup script log

/var/backups/contaneta/    # DB + storage backups (7 day rotation)
```

## Production .env (required values)

```bash
ENV=prod
DEV_MODE=0
ALLOW_DEMO_PORTAL=0
SESSION_SECRET=<python3 -c "import secrets; print(secrets.token_hex(32))">
AT_REST_MASTER_KEY=<python3 -c "import secrets; print(secrets.token_hex(32))">
APP_DB_PATH=/var/lib/contaneta/invoicing.db
APP_STORAGE_PATH=/var/lib/contaneta/storage
BACKUP_DIR=/var/backups/contaneta
COOKIE_SECURE=1
SITE_URL=https://YOUR_DOMAIN.com
ADMIN_PASSWORD=<strong-password>
```

## Services

| Service | Type | Description |
|---------|------|-------------|
| `contaneta-web` | daemon | Gunicorn (1 worker + 4 threads) on :8000 |
| `contaneta-sat-worker` | daemon | Job queue processor (polls every 2s) |
| `contaneta-sat-scheduler.timer` | timer | Enqueues SAT sync every 10 min |
| `contaneta-backup.timer` | timer | Nightly DB + storage backup at 3 AM |

```bash
# Check status
sudo systemctl status contaneta-web contaneta-sat-worker
sudo systemctl list-timers contaneta-*

# View logs
journalctl -u contaneta-web -f
journalctl -u contaneta-sat-worker -f
tail -f /var/log/contaneta/web.log

# Restart after code update
sudo systemctl restart contaneta-web contaneta-sat-worker
```

## Reverse Proxy: Caddy vs Nginx

**Caddy (recommended)** — automatic HTTPS, zero config TLS:
```bash
sudo cp deploy/caddy/Caddyfile /etc/caddy/Caddyfile
# Edit domain, then:
sudo systemctl reload caddy
```

**Nginx (alternative)** — if you prefer:
```bash
sudo cp deploy/nginx/contaneta.conf /etc/nginx/sites-available/contaneta
sudo ln -sf /etc/nginx/sites-available/contaneta /etc/nginx/sites-enabled/
sudo certbot --nginx -d YOUR_DOMAIN.com
sudo systemctl reload nginx
```

## Gunicorn Notes (SQLite)

- **1 worker** is required because SQLite doesn't support concurrent writers
- Use `--threads 4` for concurrency within the single worker
- WAL mode is enabled for concurrent reads
- If you ever migrate to PostgreSQL, increase to `-w 4` workers

## Verification

```bash
# Health check
curl -s http://localhost:8000/health | python3 -m json.tool

# Full smoke test
cd /opt/contaneta && BASE_URL=https://YOUR_DOMAIN bash scripts/smoke_release.sh

# SAT scheduler dry run
sudo -u contaneta /opt/contaneta/.venv/bin/python scripts/sat_scheduler.py --dry-run

# Check jobs
sudo -u contaneta sqlite3 /var/lib/contaneta/invoicing.db \
  "SELECT status, COUNT(*) FROM sat_jobs GROUP BY status;"
```

## Updates

```bash
cd /opt/contaneta
sudo -u contaneta git pull
sudo -u contaneta .venv/bin/pip install -r requirements.txt
sudo systemctl restart contaneta-web contaneta-sat-worker
# Migrations run automatically on app startup
```
