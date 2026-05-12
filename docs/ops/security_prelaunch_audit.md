# Security Pre-Launch Audit

**Date:** 2026-05-12
**Scope:** 10 security areas not covered by existing audits
**Overall Posture:** GOOD — strong fundamentals, few medium-risk gaps

## Summary Table

| # | Area | Status | Risk | Fix Effort |
|---|------|--------|------|------------|
| 1 | Rate limiting on uploads | Secure | Medium | Low |
| 2 | MIME/file type validation | Partial | Medium | Low |
| 3 | SSRF in configurable URLs | Secure | Low | — |
| 4 | PII in logs | Secure | Low | — |
| 5 | SQL injection (f-strings) | Secure | Low | — |
| 6 | CORS configuration | Secure | Low | — |
| 7 | Subprocess security | Secure | Low | — |
| 8 | File path traversal | Secure | Low | — |
| 9 | Session/cookie security | Secure | Medium | Medium |
| 10 | Upload size limits | Secure | Low | — |

## Hard Blockers (Fix Before Launch)

None identified. No critical vulnerabilities found.

## Strongly Recommended (Fix in First Month Post-Launch)

### 1. FIEL Certificate Format Validation (MEDIUM)
**File:** `routers/portal/sat_config.py:274-281`
**Issue:** `.cer` and `.key` files validated by extension and size only. No check that content is a valid X.509 certificate or PKCS#8 key.
**Risk:** Arbitrary binary files could be uploaded (stored encrypted). Runtime failure when PHP subprocess tries to use them.
**Fix:** Add `cryptography` library validation after reading file bytes:
```python
from cryptography import x509
x509.load_der_x509_certificate(cer_body)  # SAT .cer files are DER format
```
**Effort:** Low (5-10 lines of code)

### 2. X-Forwarded-For Proxy Validation (MEDIUM)
**File:** `services/rate_limit.py`
**Issue:** Rate limiting trusts X-Forwarded-For header from any client. Behind Caddy this is fine, but direct access could spoof IPs.
**Risk:** Rate limit bypass by spoofing source IP.
**Fix:** Validate X-Forwarded-For only from trusted proxy IPs (Caddy/LB). In production behind Caddy, Caddy overwrites the header, so risk is mitigated.
**Effort:** Low

### 3. Session Invalidation on Password Change (MEDIUM)
**File:** `services/auth/session.py`
**Issue:** Changing password does not invalidate existing sessions. Stolen session cookie remains valid for up to 7 days.
**Risk:** If session is compromised, password change alone doesn't revoke attacker access.
**Fix:** Add session version counter to user record; increment on password change; reject sessions with old version.
**Effort:** Medium (migration + session check logic)

## Nice to Have (Post-Launch)

### 4. Comprehensive PII Scrubbing in Error Events (LOW)
**File:** `services/error_events.py:60-61`
**Issue:** Error event scrubber handles tokens/passwords but could miss RFCs, emails in exception messages.
**Fix:** Add regex patterns for RFC (`[A-Z]{3,4}[0-9]{6}[A-Z0-9]{3}`) and email to scrubber.
**Effort:** Low

### 5. Rate Limit Response Headers (LOW)
**Issue:** No `RateLimit-*`, `Retry-After` headers returned when rate limited.
**Fix:** Add headers per IETF draft (RateLimit-Limit, RateLimit-Remaining, Retry-After).
**Effort:** Low

## Areas Confirmed Secure

### SQL Injection
All queries use `?` parameterized placeholders for user input. F-strings used only for table/column names validated against whitelists (`_SAFE_UPDATE_TABLES`, `ALLOWED_CATALOG_TABLES`). **No injection vectors found.**

### Subprocess Execution
All SAT PHP calls use `subprocess.Popen()` with:
- Arguments as list (no shell interpretation)
- `shell=False` (enforced, no `shell=True` anywhere)
- Mandatory timeouts (30-120s)
- Process killed on timeout (`proc.kill()`)

### File Path Traversal
`safe_join()` helper used everywhere: normalizes paths, validates prefix under root directory. Prevents `../` escapes.

### Upload Size Limits
All upload endpoints enforce size limits **during streaming** (not post-write):
- FIEL: 2 MB
- Bank PDF: 15 MB (single), 50 MB (multi)
- Month-close PDF: 10 MB
- Invoice PDF: 15 MB

### CORS
Not configured — not needed for server-rendered portal. Same-Origin Policy applies by default.

### PII in Logs
No RFCs, emails, or passwords found in log statements. Password failures log user_id only. Error event scrubber strips tokens and secrets.

### SSRF
No `urllib.urlopen()`, `requests.get()`, or similar calls in application code. The only external HTTP call is `banxico_client.py` which uses hardcoded Banxico API URL (not user-controllable).
