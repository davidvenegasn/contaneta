# LFPDPPP Compliance Audit — ContaNeta

**Date:** 2026-05-12
**Law:** Ley Federal de Protección de Datos Personales en Posesión de los Particulares

## Personal Data Inventory

### Tables with Datos Personales

| Table | PII Fields | Encrypted? |
|-------|-----------|-----------|
| `users` | email, phone, name, password_hash | password hashed (bcrypt) |
| `issuers` | rfc, razon_social | No |
| `customer_profiles` | rfc, legal_name, email, zip | No |
| `supplier_profiles` | rfc, legal_name, email, zip | No |
| `issuer_bank_accounts` | clabe, holder_name, rfc_titular | clabe encrypted (AES-GCM) |
| `sat_credentials` | fiel_cer_path, fiel_key_path, fiel_key_password | All encrypted (AES-GCM) |
| `invoices` | customer_rfc, customer_legal_name, customer_email | No |
| `quotations` | customer_rfc, customer_legal_name, customer_email, decision_ip | No |
| `sat_cfdi` | rfc_emisor, nombre_emisor, rfc_receptor, nombre_receptor | No |
| `bank_movements` | rfc_encontrado, contraparte_hint | No |
| `foreign_invoices` | empresa, tax_id | No |
| `audit_log` | user_id, issuer_id, action, details | No |
| `file_access_log` | user_id, issuer_id, file_path | No |

### Data Ingestion Points

1. **Registration**: email, phone, password, name
2. **Issuer setup**: RFC, razon social, FIEL credentials, bank accounts
3. **Customer/supplier profiles**: RFC, legal name, email, postal code
4. **Invoice/quotation creation**: customer RFC, name, email
5. **SAT sync**: all CFDI data (RFCs, names) from Mexico SAT
6. **Bank movements**: parsed counterparty RFCs

## Current Security Measures (Positive)

| Measure | Status |
|---------|--------|
| Password hashing (bcrypt) | Implemented |
| FIEL encryption (AES-256-GCM, per-tenant keys) | Implemented |
| Bank CLABE encryption (AES-256-GCM) | Implemented |
| HMAC-signed session cookies | Implemented |
| CSRF protection (HMAC, 1h TTL) | Implemented |
| Tenant isolation (issuer_id filter on all queries) | Implemented |
| HttpOnly + SameSite=Lax + Secure cookies | Implemented |
| Security headers (CSP, X-Frame-Options, etc.) | Implemented |
| Rate limiting on auth endpoints | Implemented |
| Audit logging for admin actions | Implemented |
| File access logging | Implemented |

## LFPDPPP Compliance Gaps

### Derechos ARCO (Arts. 22-35)

| Right | Article | Status | Action Required |
|-------|---------|--------|----------------|
| **Acceso** (Access) | Art. 23 | NOT IMPLEMENTED | Data export endpoint |
| **Rectificación** (Rectification) | Art. 25 | PARTIAL | User can edit profile; customer data editable |
| **Cancelación** (Deletion) | Art. 26 | NOT IMPLEMENTED | Account deletion + data anonymization |
| **Oposición** (Objection) | Art. 27 | NOT IMPLEMENTED | Consent withdrawal mechanism |

### Other Requirements

| Requirement | Article | Status |
|-------------|---------|--------|
| Aviso de privacidad | Arts. 15-18 | NOT IMPLEMENTED |
| Consent tracking | Art. 8 | NOT IMPLEMENTED |
| Data retention policy | Art. 37-IV | NOT IMPLEMENTED |
| Breach notification | Art. 20 | NOT IMPLEMENTED |
| Data transfer agreements | Arts. 36-37 | NOT DOCUMENTED |
| DPO designation | Art. 30 | NOT DESIGNATED |

## Implementation Roadmap

### Phase 1 — Immediate (Required for Launch)

1. **Aviso de Privacidad** (privacy notice page)
   - Static page at `/privacidad` listing: data collected, purposes, retention, ARCO rights contact
   - Link in footer of all portal pages
   - Consent checkbox on registration form

2. **Account deletion request table**
   - Migration: `account_deletion_requests` (user_id, requested_at, status, completed_at)
   - Request endpoint: `POST /api/account/delete-request`
   - Manual processing initially (owner reviews + executes)

3. **Data export endpoint**
   - `GET /api/account/my-data` → JSON with user profile, memberships, audit log entries
   - Rate-limited (1 per day)

### Phase 2 — Short-Term (Within 90 Days)

4. **Consent tracking table**
   - `user_consents` (user_id, consent_type, version, accepted_at, ip_address)
   - Types: `privacy_policy`, `terms_of_service`, `marketing`
   - Enforce acceptance on login if version changed

5. **Data retention cleanup job**
   - `email_verifications` / `password_resets`: delete used tokens after 30 days
   - `notifications`: archive after 90 days
   - `audit_log`: retain 7 years (CFF Art. 30 — tax obligation)
   - `file_access_log`: retain 2 years

6. **Automated account deletion**
   - Cascade: anonymize user → deactivate memberships → anonymize audit references
   - Retain fiscal data (invoices, CFDI) per CFF Art. 30 (5-year minimum)

### Phase 3 — Medium-Term

7. Encrypt remaining PII at rest (customer emails, RFCs beyond FIEL/CLABE)
8. Data Processing Agreements with Stripe, SMTP provider
9. Breach notification workflow
10. Annual LFPDPPP compliance review process

## Legal Retention Conflicts

Mexican tax law (Código Fiscal de la Federación, Art. 30) requires retaining fiscal documentation for **5 years** from the date of the last tax return. This conflicts with the right to deletion:

- **Invoices / CFDI**: Must retain 5 years → cannot delete on ARCO request
- **User account data**: Can be anonymized (replace name/email with "DELETED")
- **Bank movements**: Retain for fiscal reconciliation → anonymize counterparty data after retention period

**Resolution**: On deletion request, anonymize PII but retain fiscal records with anonymized references. Document this in the Aviso de Privacidad.

## Third-Party Data Processors

| Processor | Data Shared | Purpose | DPA Status |
|-----------|------------|---------|-----------|
| SAT (Mexico) | RFC, FIEL credentials | Tax compliance | Government — no DPA needed |
| Stripe | Email, subscription data | Billing | Stripe DPA available |
| SMTP provider | Email addresses | Notifications | DPA needed |

## Risk Assessment

| Risk | Severity | Likelihood | Mitigation |
|------|----------|-----------|-----------|
| No deletion mechanism | HIGH | MEDIUM | Phase 1 — deletion request table |
| No privacy notice | HIGH | HIGH | Phase 1 — static page |
| No consent tracking | MEDIUM | MEDIUM | Phase 2 — consent table |
| PII unencrypted at rest | LOW | LOW | Multi-tenant isolation + DB access control |
| No breach notification | MEDIUM | LOW | Phase 3 — incident response plan |
