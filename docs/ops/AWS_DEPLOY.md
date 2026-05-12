# AWS Deployment Guide — ContaNeta

## Architecture Overview

```
Route 53 → ALB (HTTPS) → EC2 (t3.small) → Gunicorn + Uvicorn
                                          ↘ SQLite (EBS gp3)
                                          ↘ Worker (systemd)
S3 → Backups (daily)
```

Single-instance deployment with SQLite. For <500 users this is simpler and cheaper than RDS.

## Prerequisites

- AWS account with IAM user (programmatic access)
- Domain pointed to Route 53 (or external DNS)
- `aws` CLI configured locally
- SSH key pair created in EC2 console

## 1. Launch EC2 Instance

```bash
# Ubuntu 22.04 LTS, t3.small (2 vCPU, 2 GB RAM)
aws ec2 run-instances \
  --image-id ami-0c7217cdde317cfec \
  --instance-type t3.small \
  --key-name your-key \
  --security-group-ids sg-xxxx \
  --subnet-id subnet-xxxx \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":30,"VolumeType":"gp3"}}]' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=contaneta-prod}]'
```

### Security Group Rules

| Type  | Port | Source        | Description       |
|-------|------|---------------|-------------------|
| SSH   | 22   | Your IP       | Admin access      |
| HTTPS | 443  | 0.0.0.0/0     | Public traffic    |
| HTTP  | 80   | 0.0.0.0/0     | Redirect to HTTPS |

## 2. Server Setup

```bash
ssh -i your-key.pem ubuntu@<public-ip>

# System packages
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3-pip nginx certbot python3-certbot-nginx

# App user
sudo useradd -m -s /bin/bash contaneta
sudo mkdir -p /opt/contaneta
sudo chown contaneta:contaneta /opt/contaneta

# Clone and setup
sudo -u contaneta git clone <repo-url> /opt/contaneta/app
cd /opt/contaneta/app
sudo -u contaneta python3.11 -m venv .venv
sudo -u contaneta .venv/bin/pip install -r requirements.txt
```

## 3. Environment Configuration

```bash
sudo -u contaneta cp .env.example /opt/contaneta/app/.env
sudo -u contaneta nano /opt/contaneta/app/.env
```

Required variables:
```
ENV=prod
DEV_MODE=0
SESSION_SECRET=<generate with: python3 -c "import secrets; print(secrets.token_hex(32))">
APP_DB_PATH=/opt/contaneta/data/invoicing.db
SITE_URL=https://your-domain.com
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID=price_...
```

## 4. Systemd Services

### Web Service

```ini
# /etc/systemd/system/contaneta.service
[Unit]
Description=ContaNeta Web
After=network.target

[Service]
Type=exec
User=contaneta
WorkingDirectory=/opt/contaneta/app
ExecStart=/opt/contaneta/app/.venv/bin/gunicorn app:app \
  -k uvicorn.workers.UvicornWorker \
  --bind 127.0.0.1:8000 \
  --workers 2 \
  --timeout 120 \
  --access-logfile /var/log/contaneta/access.log \
  --error-logfile /var/log/contaneta/error.log
Restart=always
RestartSec=5
EnvironmentFile=/opt/contaneta/app/.env

[Install]
WantedBy=multi-user.target
```

### Worker Service

```ini
# /etc/systemd/system/contaneta-worker.service
[Unit]
Description=ContaNeta Worker
After=contaneta.service

[Service]
Type=exec
User=contaneta
WorkingDirectory=/opt/contaneta/app
ExecStart=/opt/contaneta/app/.venv/bin/python worker.py --loop
Restart=always
RestartSec=10
EnvironmentFile=/opt/contaneta/app/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo mkdir -p /var/log/contaneta
sudo chown contaneta:contaneta /var/log/contaneta
sudo systemctl daemon-reload
sudo systemctl enable contaneta contaneta-worker
sudo systemctl start contaneta contaneta-worker
```

## 5. Nginx + SSL

```nginx
# /etc/nginx/sites-available/contaneta
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    client_max_body_size 20M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        alias /opt/contaneta/app/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/contaneta /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d your-domain.com
```

## 6. Backups to S3

```bash
# Create S3 bucket
aws s3 mb s3://contaneta-backups-prod --region us-east-1

# Daily backup cron (as contaneta user)
# See scripts/backup_to_s3.sh.example for full script
crontab -e
# 0 3 * * * /opt/contaneta/app/scripts/backup_to_s3.sh.example
```

## 7. Monitoring

```bash
# CloudWatch agent for logs
sudo apt install -y amazon-cloudwatch-agent

# Health check (add to cron)
# */5 * * * * curl -sf https://your-domain.com/health || echo "ALERT: ContaNeta down" | mail admin@example.com
```

## 8. Deploy Updates

```bash
ssh -i your-key.pem ubuntu@<public-ip>
cd /opt/contaneta/app
sudo -u contaneta git pull origin main
sudo -u contaneta .venv/bin/pip install -r requirements.txt
sudo systemctl restart contaneta contaneta-worker
# Migrations run automatically on startup
curl -sf https://your-domain.com/health && echo "Deploy OK"
```

## Cost Estimate (monthly)

| Resource         | Cost      |
|------------------|-----------|
| EC2 t3.small     | ~$15      |
| EBS 30 GB gp3    | ~$2.40    |
| ALB (optional)   | ~$16      |
| S3 backups       | ~$0.50    |
| Route 53         | ~$0.50    |
| **Total**        | **~$18-35** |

## Security Checklist

- [ ] Security group restricts SSH to admin IPs only
- [ ] .env file is chmod 600
- [ ] SSL certificate auto-renews (certbot timer)
- [ ] S3 bucket has versioning enabled
- [ ] CloudWatch alerts on disk >80%
- [ ] Regular `apt upgrade` schedule
