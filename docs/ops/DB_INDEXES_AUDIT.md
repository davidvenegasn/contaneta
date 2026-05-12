# Database Indexes Audit — ContaNeta

**Date:** 2026-05-12 | **Database:** SQLite (WAL mode)

## Summary

60+ indexes exist across all tables. 3 high-priority indexes are missing on hot paths.

## Existing Coverage (Good)

| Table | Key Indexes | Status |
|-------|-------------|--------|
| sat_cfdi | `(issuer_id, direction, fecha_emision)`, `(issuer_id, uuid)` | Good |
| bank_movements | `(issuer_id, period_month)`, `(issuer_id, fecha)`, `(issuer_id, categoria)` | Good |
| jobs | `(status, run_after)`, `(issuer_id, created_at DESC)` | Partial |
| customer_profiles | `(issuer_id)`, `(alias)` | Partial |
| invoices | `(issuer_id, uuid)`, `(issuer_id, payment_method)` | Good |
| notifications | `(issuer_id, read_at, created_at)` | Good |

## Recommended New Indexes

### HIGH Priority

| Index | Table | Columns | Rationale |
|-------|-------|---------|-----------|
| `idx_jobs_issuer_name_hash_status` | jobs | `(issuer_id, name, payload_hash, status)` | Worker dedupe/claim — every few seconds |
| `idx_sat_cfdi_issuer_direction_status` | sat_cfdi | `(issuer_id, direction, status)` | Admin dashboard counts, portal deduction checks |
| `idx_customer_profiles_issuer_rfc` | customer_profiles | `(issuer_id, rfc)` | Invoice creation, catalog sync lookups |

### MEDIUM Priority

| Index | Table | Columns | Rationale |
|-------|-------|---------|-----------|
| `idx_bank_movements_issuer_period_cat` | bank_movements | `(issuer_id, period_month, categoria)` | Reconciliation aggregations |
| `idx_invoices_issuer_pm_date` | invoices | `(issuer_id, payment_method, issue_date DESC)` | Pending invoice listings |

### LOW Priority

| Index | Table | Columns | Rationale |
|-------|-------|---------|-----------|
| `idx_sat_cfdi_issuer_tipo` | sat_cfdi | `(issuer_id, tipo_comprobante, direction)` | Deduction type checks |
| `idx_jobs_issuer_status_created` | jobs | `(issuer_id, status, created_at DESC)` | Admin job monitoring |

## Redundant Indexes (Consider Removing)

1. `idx_bank_movements_issuer` — redundant with composite indexes on same table
2. `idx_sat_jobs_issuer` — defined twice in migrations with different columns
3. `idx_sat_cfdi_issuer_date` — possibly redundant with `idx_sat_cfdi_issuer_dir_fecha`

## Storage Impact

~20-50MB total for all recommended indexes at current data volumes (<1M rows per table).

## Implementation

See `migrations/0XX_add_performance_indexes.sql.example` for ready-to-use migration.
