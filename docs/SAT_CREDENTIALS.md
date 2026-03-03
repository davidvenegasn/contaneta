# SAT Credentials (FIEL/CSD) — Security Documentation

## Overview

FIEL (Firma Electrónica) credentials are used to authenticate with Mexico's SAT (tax authority) for CFDI sync. Each issuer uploads `.cer` (certificate), `.key` (private key), and a password. These are stored **encrypted at rest** using AES-256-GCM with per-issuer key derivation.

## Architecture

```
Upload (portal)           Storage (disk)              Usage (PHP subprocess)
─────────────────        ──────────────────          ─────────────────────────
fiel.cer  ──encrypt──►   fiel.cer.enc  (0o600)
fiel.key  ──encrypt──►   fiel.key.enc  (0o600)      decrypted_fiel_env()
password  ──encrypt──►   enc:v1:<nonce>.<ct> (DB)      ├─ decrypt to temp files
                                                       ├─ pass as env vars to PHP
                                                       └─ cleanup temp files
```

## Encryption Scheme

| Component | Algorithm | Details |
|-----------|-----------|---------|
| File encryption | AES-256-GCM | 12-byte random nonce, AAD = `b"fiel.cer"` or `b"fiel.key"` |
| Password encryption | AES-256-GCM | Stored as `enc:v1:<nonce_b64>.<ct_b64>` token |
| Key derivation | HKDF-SHA256 | Per-issuer: `info=b"issuer:<id>"`, `salt=b"contaneta:at-rest:v1"` |
| Master key | `AT_REST_MASTER_KEY` env | 32 bytes (hex or base64url). Fallback: `SHA256(SESSION_SECRET)` |
| Binary format | `CNENC1` + nonce(12) + ciphertext | Magic bytes prefix for identification |

### Key Hierarchy

```
AT_REST_MASTER_KEY (or SHA256(SESSION_SECRET))
    └── HKDF(master, salt="contaneta:at-rest:v1", info="issuer:<id>")
            └── Per-issuer AES-256-GCM key (32 bytes)
```

### Implementation Files

| File | Purpose |
|------|---------|
| `services/crypto_at_rest.py` | Core crypto: encrypt/decrypt bytes and text, key derivation |
| `services/sat_credentials_secure.py` | FIEL-specific: lazy migration, context manager for PHP |
| `routers/portal.py` (lines ~3920-4045) | Upload endpoint, validation trigger |

## Upload Flow

```
1. POST /portal/settings/fiel-upload
2. Rate limit: 10 attempts/60s per IP (key: "fiel_upload:<IP>")
3. Validate file extensions (.cer, .key) and size (max 2 MB each)
4. Validate password is not empty
5. Encrypt .cer with AES-256-GCM (AAD = b"fiel.cer") → fiel.cer.enc
6. Encrypt .key with AES-256-GCM (AAD = b"fiel.key") → fiel.key.enc
7. Encrypt password → enc:v1:<nonce>.<ct> token
8. Store paths + encrypted password in sat_credentials table (UPSERT)
9. Set file permissions to 0o600
10. Trigger validation (check_fiel.php) → store result
11. Audit log: action="credentials_uploaded"
```

## Validation Flow

```
1. POST /portal/settings/fiel-validate (or auto after upload)
2. decrypted_fiel_env(issuer_id) context manager:
   a. ensure_fiel_encrypted() — lazy migration if needed
   b. Decrypt .cer.enc → temp file (0o600)
   c. Decrypt .key.enc → temp file (0o600)
   d. Decrypt password → plaintext string
   e. Set env vars: SAT_FIEL_CER_PATH, SAT_FIEL_KEY_PATH, SAT_FIEL_PASSWORD
3. Run sat_sync/check_fiel.php via subprocess (30s timeout)
4. Cleanup: temp files deleted in finally block
5. Update sat_credentials: validation_ok, validation_at, validation_message
6. Audit log: action="credentials_validated"
```

## Lazy Encryption Migration

`ensure_fiel_encrypted()` automatically migrates legacy plaintext credentials:

1. If password doesn't start with `enc:` → encrypt and update DB
2. If `.cer`/`.key` files exist without `.enc` extension → encrypt, save `.enc`, delete originals, update DB paths
3. Migration is idempotent — already-encrypted files are skipped

## File Storage Layout

```
storage/credentials/<issuer_id>/
├── fiel.cer.enc    (AES-256-GCM encrypted, 0o600)
└── fiel.key.enc    (AES-256-GCM encrypted, 0o600)
```

Database (`sat_credentials` table):

| Column | Content |
|--------|---------|
| `fiel_cer_path` | Relative path: `storage/credentials/<id>/fiel.cer.enc` |
| `fiel_key_path` | Relative path: `storage/credentials/<id>/fiel.key.enc` |
| `fiel_key_password` | Encrypted token: `enc:v1:<nonce_b64>.<ct_b64>` |
| `validation_ok` | `1` (valid) or `0` (invalid) |
| `validation_at` | Last validation timestamp |
| `validation_message` | Human-readable validation result |

## Security Properties

| Property | Implementation |
|----------|---------------|
| Encryption at rest | AES-256-GCM for files and password |
| Per-tenant isolation | HKDF derives unique key per issuer_id |
| AAD binding | Certificate and key have distinct AAD (`fiel.cer`, `fiel.key`) |
| File permissions | `0o600` on all credential files (encrypted and temp) |
| Temp file cleanup | `finally` block in context manager guarantees deletion |
| No password logging | Password values never appear in logs |
| Upload size limit | 2 MB max per file |
| Rate limiting | 10 uploads/60s per IP |
| Audit trail | Upload and validation events logged with `action_log` |
| Magic bytes | `CNENC1` prefix identifies encrypted blobs |

## Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `AT_REST_MASTER_KEY` | Recommended | Derived from `SESSION_SECRET` | 32-byte master key (hex or base64url) |
| `SESSION_SECRET` | **Prod: YES** | dev fallback | Fallback for key derivation if `AT_REST_MASTER_KEY` not set |

## Operational Notes

### Key Rotation

Changing `AT_REST_MASTER_KEY` or `SESSION_SECRET` (when used as fallback) **invalidates all encrypted credentials**. To rotate:

1. Decrypt all credentials with old key
2. Update environment variable
3. Re-encrypt with new key
4. Or: delete credentials and have users re-upload

### Backup Considerations

- Encrypted credential files (`.enc`) can be safely included in backups
- The master key (`AT_REST_MASTER_KEY` / `SESSION_SECRET`) must **not** be stored in the same backup
- Without the master key, encrypted files are unrecoverable

### Dependency

Requires `cryptography` Python package (for AESGCM, HKDF). If missing, encryption operations raise `RuntimeError` with a clear message.
