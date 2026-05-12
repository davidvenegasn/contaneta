# SAT Credentials Security Audit — ContaNeta

**Date:** 2026-05-12 | **Status:** GOOD overall, 1 HIGH bug found

## Encryption

- **Algorithm**: AES-256-GCM via `cryptography.hazmat.primitives.ciphers.aead.AESGCM`
- **Key derivation**: HKDF-SHA256, per-tenant keys from master key + `issuer:{id}` info
- **Nonces**: 12 bytes from `os.urandom()` (cryptographically secure)
- **AAD binding**: `b"fiel.cer"` and `b"fiel.key"` — prevents cross-type confusion
- **Storage**: `.cer.enc` and `.key.enc` blobs in DB; password as `enc:v1:<nonce>.<ciphertext>`

## Master Key

| Scenario | Source | Secure? |
|----------|--------|---------|
| Production | `AT_REST_MASTER_KEY` env var (required — RuntimeError if missing) | YES |
| Development | Falls back to `SHA256(SESSION_SECRET)` | Acceptable for dev |

**No hardcoded keys found anywhere in codebase.**

## Findings

### HIGH: Upload validation constants undefined after portal split
`ALLOWED_CER`, `ALLOWED_KEY`, `MAX_FIEL_SIZE` are used in `sat_config.py` but not defined or imported. Upload endpoint throws `NameError`. File extension and size validation not running.

**Fix needed**: Define constants in `sat_config.py`:
```python
ALLOWED_CER = (".cer",)
ALLOWED_KEY = (".key",)
MAX_FIEL_SIZE = 2 * 1024 * 1024  # 2 MB
```

### MEDIUM: Temp files not securely wiped
`os.remove()` unlinks but doesn't overwrite. Plaintext credentials recoverable from disk until overwritten by OS. Context manager `finally` block ensures cleanup even on exceptions.

### MEDIUM: debug_verify.php bypasses encrypted credential flow
Reads `fiel_key_password` directly from DB (not via env override). Should not exist in production.

### LOW: Silent failure on temp file deletion
`except Exception: pass` in cleanup — if `os.remove()` fails, plaintext stays on disk with no warning.

### LOW: run_parse_only() decrypts FIEL unnecessarily
XML parsing doesn't need FIEL credentials but wraps in `decrypted_fiel_env()`.

## Verification Summary

| Check | Result |
|-------|--------|
| Credentials encrypted AES-GCM before storage | ✅ |
| Master key from env, not hardcoded | ✅ |
| No FIEL in logs (searched logger calls) | ✅ |
| Temp files deleted after subprocess | ✅ (context manager) |
| Upload validates size and extension | ❌ (constants missing after split) |
| Path traversal blocked for credential dirs | ✅ |
| .gitignore excludes storage/ and keys/ | ✅ |
