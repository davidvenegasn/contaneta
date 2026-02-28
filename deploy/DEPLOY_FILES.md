# Deploy Files — what goes to production

## INCLUDE (deployable)

```
app.py
config.py
database.py
facturapi_client.py
cfdi_pdf.py
validators.py
migrations_runner.py
worker.py
run_server.sh
requirements.txt

routers/            (all .py)
services/           (all .py)
templates/          (all .html)
static/             (css/, js/, img/)
migrations/         (all .sql)
catalogs/catalogs.db
sat_sync/           (all .php, .sh)
deploy/             (systemd, nginx, caddy configs)
scripts/safe_export.sh
```

## NEVER INCLUDE

```
.env                    # secrets (SESSION_SECRET, STRIPE keys, DB creds)
storage/                # uploaded files, FIEL certs, XML, PDFs
storage/credentials/    # encrypted FIEL .cer/.key
backup/                 # DB and storage backups
sqlite_aux_backup/      # auxiliary DB backups
invoicing.db*           # application database
*.log                   # server/worker logs
.venv/ / venv/          # Python virtual environment
__pycache__/            # bytecode cache
keys/                   # signing keys
_snapshot_*/            # dev snapshots
.claude/                # AI tool config
tests/                  # test suite (not needed in prod)
scripts/*.py            # dev/debug scripts
docs/                   # internal documentation
```

## Pre-deploy checklist

1. Ensure `.env` is configured on server (not shipped)
2. Run `scripts/safe_export.sh` to generate zip
3. Verify zip does NOT contain `.env`, `storage/`, `*.db` (except catalogs.db)
4. Upload, extract, `pip install -r requirements.txt`, restart service
