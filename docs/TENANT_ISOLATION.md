# Multi-Tenant Isolation — ContaNeta

## Model

Tenant = **Issuer** (a company identified by RFC). Every data table that holds tenant-specific data includes an `issuer_id` column. Every query filters by `issuer_id`.

```
Session Cookie (HMAC-SHA256)
  └── user_id | issuer_id | expiry
        │         │
        ▼         ▼
  get_portal_issuer()  ──►  request.state.issuer_id
                              request.state.user_id
                              request.state.membership_role
```

## Isolation Enforcement

### Layer 1: Authentication (`routers/deps.py`)

All portal and API routes use `Depends(get_portal_issuer)` which:
1. Verifies the session cookie (HMAC signature + expiry)
2. Resolves `issuer_id` from the cookie
3. Verifies user membership for that issuer
4. Sets `request.state.issuer_id` for downstream use

### Layer 2: SQL Queries

Every SELECT, UPDATE, and DELETE that touches tenant data includes `WHERE issuer_id = ?`. This is enforced by convention — there is no ORM or middleware that auto-applies the filter.

**Pattern (correct):**
```python
issuer_id = request.state.issuer_id
rows = db_rows("SELECT * FROM clients WHERE issuer_id = ?", (issuer_id,))
```

**Anti-pattern (never do this):**
```python
# WRONG: no issuer_id filter — leaks data across tenants
rows = db_rows("SELECT * FROM clients WHERE id = ?", (client_id,))
```

### Layer 3: Path-based File Isolation

All file storage is scoped by issuer_id:
```
storage/
├── credentials/<issuer_id>/     # FIEL .cer/.key (encrypted)
├── xml/<issuer_id>/             # SAT CFDI XMLs
├── pdfs/<issuer_id>/            # Generated PDFs
└── bank/<issuer_id>/            # Bank statements
```

File download endpoints verify `issuer_id` ownership before serving files, and `_safe_abs_path()` prevents path traversal attacks.

### Layer 4: Service Functions

All service functions that access tenant data take `issuer_id` as an explicit parameter:
```python
# services/clients_service.py
def list_clients(issuer_id: int) -> list[dict]:
    return db_rows("SELECT ... WHERE issuer_id = ?", (issuer_id,))
```

## Audit Results

Full audit of all endpoints (March 2026):

### API Routes (`routers/api.py`)

| Endpoint | Isolation |
|----------|-----------|
| `GET /api/account/status` | issuer_id from session |
| `GET /api/jobs` | `list_jobs(issuer["id"])` |
| `GET /api/jobs/{id}` | `get_job_for_issuer(id, issuer["id"])` — double filter |
| `GET /api/customers` | `WHERE issuer_id = ?` |
| `POST /api/customers/create` | INSERT with `issuer["id"]` |
| `POST /api/customers/delete` | `DELETE WHERE issuer_id = ? AND rfc = ?` |
| `GET /api/products` | `list_products(issuer_id)` |
| `POST /api/products/create` | INSERT with `issuer["id"]` |
| `POST /api/products/delete` | `DELETE WHERE issuer_id = ? AND id = ?` |
| `GET /api/quick-invoice/bootstrap` | All queries filter by `issuer_id` |
| `POST /api/invoices/quick` | All ops use `issuer_id` |
| `POST /api/invoices/bulk_issue` | All queries filter by `issuer_id` |
| `GET /api/quotations` | `WHERE issuer_id = ?` |
| `POST /api/quotations/create` | INSERT with `issuer_id` |
| `GET /api/quotations/{id}` | `WHERE issuer_id = ? AND id = ?` |
| `POST /api/quotations/update-status` | `UPDATE WHERE issuer_id = ? AND id = ?` |
| `POST /api/quotations/respond` | Public endpoint — access via 256-bit token |
| `GET /api/provider-invoices` | `WHERE issuer_id = ?` |
| `GET /api/providers` | `WHERE issuer_id = ?` |
| `POST /api/providers/create` | INSERT with `issuer["id"]` |
| `GET /api/invoices/issued` | `WHERE issuer_id = ?` |
| `GET /api/invoices/received` | `WHERE issuer_id = ?` |
| `GET /api/invoices/pending` | `WHERE issuer_id = ?` |
| `GET /api/catalogs/*` | Read-only SAT data — no tenant scoping needed |
| `GET /api/month-close` | `get_full_month_close(issuer_id, ym)` |
| `POST /api/month-close` | `save_month_close(issuer_id, ...)` |
| `GET /api/notifications` | `list_notifications(issuer_id)` |
| `POST /api/notifications/{id}/read` | `mark_read(issuer_id, id)` |

### Portal Routes (`routers/portal.py`)

| Endpoint | Isolation |
|----------|-----------|
| `GET /portal/home` | All queries filter by `issuer_id` |
| `GET /portal/invoices/issued` | `WHERE issuer_id = ?` |
| `GET /portal/invoices/received` | `WHERE issuer_id = ?` |
| `GET /portal/facturas` | `WHERE issuer_id = ?` |
| `GET /portal/contactos` | `WHERE issuer_id = ?` |
| `GET /portal/clients` | `WHERE issuer_id = ?` |
| `GET /portal/products` | `WHERE issuer_id = ?` |
| `POST /portal/clients/save` | INSERT/UPDATE with `issuer_id` |
| `POST /portal/clients/{id}/delete` | `DELETE WHERE issuer_id = ? AND id = ?` |
| `POST /portal/products/save` | INSERT/UPDATE with `issuer_id` |
| `POST /portal/products/{id}/delete` | `DELETE WHERE issuer_id = ? AND id = ?` |
| `GET /portal/sat/xml/{uuid}` | `WHERE issuer_id = ?` + path traversal check |
| `GET /portal/sat/pdf/{uuid}` | `WHERE issuer_id = ?` + path traversal check |
| `GET /portal/summary` | `get_month_totals(issuer_id, ...)` |
| `GET /portal/month-close` | `WHERE issuer_id = ?` |
| `POST /portal/sat/sync` | `WHERE issuer_id = ?` |
| `GET /portal/bank/accounts` | `bank_list_accounts(issuer["id"])` |
| `POST /portal/bank/statements/ingest` | `ingest_bank_statement(issuer_id=...)` |
| Bank match/reject/confirm | `WHERE id = ? AND issuer_id = ?` |
| `PATCH /portal/bank/movements/{id}` | `WHERE id = ? AND issuer_id = ?` |
| Settings / FIEL upload | Scoped by session `issuer_id` |

### Download Routes (`routers/invoicing.py`)

| Endpoint | Isolation |
|----------|-----------|
| `GET /download/xml/{uuid}` | `WHERE issuer_id = ?` + `_safe_abs_path()` |
| `GET /download/pdf/{uuid}` | `WHERE issuer_id = ?` + `_safe_abs_path()` |
| `GET /download/{fmt}/{id}` | `WHERE issuer_id = ?` + audit log on denial |

### Intentionally Cross-Tenant

| Endpoint | Justification |
|----------|--------------|
| Admin panel (`/admin/*`) | Protected by `require_admin_or_owner` role check |
| Billing webhooks (`/webhooks/stripe`) | Stripe signature verification + globally unique IDs |
| Public quotation view (`/q/{token}`) | 256-bit unguessable token |
| SAT catalogs (`/api/catalogs/*`) | Read-only reference data shared across tenants |

## Helper: `safe_update()`

The `database.py:safe_update()` function accepts an optional `issuer_id` parameter for defense-in-depth:

```python
# Without issuer_id (use only for freshly-inserted rows)
safe_update(conn, "invoices", row_id, {"status": "issued"})

# With issuer_id (preferred for user-provided IDs)
safe_update(conn, "invoices", row_id, {"status": "issued"}, issuer_id=issuer_id)
```

## Membership Roles

| Role | Scope | Access |
|------|-------|--------|
| `owner` | Per-issuer | Full access to issuer data + settings |
| `accountant` | Per-issuer | Read/write invoices, clients, products |
| `viewer` | Per-issuer | Read-only access |
| `admin` | Cross-tenant | Admin panel, impersonation, all issuers |

Users can have multiple memberships (one per issuer). Role is checked via `request.state.membership_role`.

## Security Properties

| Property | Implementation |
|----------|---------------|
| Session binding | `issuer_id` embedded in HMAC-signed cookie |
| Query isolation | All SQL queries include `WHERE issuer_id = ?` |
| File isolation | Storage paths scoped by `issuer_id` subdirectory |
| Path traversal | `_safe_abs_path()` blocks escape from BASE_DIR |
| Credential isolation | FIEL keys encrypted with per-issuer derived key (HKDF) |
| Cross-tenant admin | Requires `admin` role + audit logged |
| Impersonation | 4-part cookie with `restore_issuer_id` + audit logged |
