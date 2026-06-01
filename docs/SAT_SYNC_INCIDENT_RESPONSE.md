# SAT Sync — Incident Response & Runbook

## Problem: metadata-only CFDIs (total=0, no XML)

### Root cause

`sync.php` (metadata sync) and `sync_xml.php` (XML download) share the
`sat_sync_state` checkpoint. When metadata sync finishes, the checkpoint
advances. `sync_xml.php` then only processes the latest window and may miss
CFDIs from earlier in the sync range. Result: CFDIs stored with `total=0.0`
and `xml_status IS NULL` ("metadata-only").

### Detection

```sql
-- Count metadata-only CFDIs per issuer
SELECT issuer_id, direction,
       COUNT(*) FILTER (WHERE xml_status IS NULL OR xml_status != 'parsed') AS metadata_only,
       COUNT(*) FILTER (WHERE xml_status = 'parsed') AS parsed
FROM sat_cfdi
GROUP BY issuer_id, direction
HAVING metadata_only > 0;
```

Or via the admin API:

```
GET /admin/sat/metadata-only-stats?issuer_id=<ID>
```

Or via the CLI:

```bash
python scripts/repair_metadata_only_cfdis.py --issuer <ID> --dry-run
```

### Resolution

#### Option A: Admin endpoint (one issuer at a time)

```
POST /admin/sat/repair-metadata-only
Body: {"issuer_id": <ID>}
```

Resets the sync checkpoint to January 1st and clears cooldown. The next
scheduled sync cycle will re-download XMLs for the affected range.

#### Option B: CLI script (batch repair)

```bash
# Dry run — see what would be repaired
python scripts/repair_metadata_only_cfdis.py --all --dry-run

# Execute repair for all affected issuers
python scripts/repair_metadata_only_cfdis.py --all

# Single issuer
python scripts/repair_metadata_only_cfdis.py --issuer 42
```

#### Option C: Full resync (user-initiated)

Users with valid FIEL can trigger a full historical resync from the portal:

1. Go to **Ajustes → Conectar SAT**
2. Click **"Resync completo"**
3. Confirm in the modal

This enqueues `sat_full_sync` jobs for both issued and received directions
with a 365-day backfill window.

#### Option D: Full resync (programmatic)

```python
from services.sat.sat_full_sync import enqueue_sat_full_sync

# Resync issued CFDIs for the last year
enqueue_sat_full_sync(issuer_id=42, direction="issued", backfill_days=365)

# Resync received
enqueue_sat_full_sync(issuer_id=42, direction="received", backfill_days=365)
```

### Prevention

The `sat_full_sync` handler (JOB 3) runs all 4 phases atomically in a single
job, preventing checkpoint interference:

1. **Metadata sync** (`sync.php`) — download CFDI metadata from SAT
2. **Checkpoint reset** — if metadata-only CFDIs exist, reset the checkpoint
3. **XML pipeline** (`sync_xml.php`) — request, verify, and download XMLs
4. **Smart retry** — if SAT returns "Sin informacion" but metadata-only CFDIs
   exist, wait 60s and retry up to 3 times

### Portal filter behavior

The portal uses the filter `(xml_status = 'parsed' OR total IS NULL OR total >= 0.01)`
to hide metadata-only CFDIs with zero total. This means:

- **Parsed CFDIs** (including credit notes with total=0): always visible
- **Metadata-only with total=0**: hidden (shown as "Procesando datos" badge if visible)
- **Metadata-only with real total (>0.01)**: visible (best-effort from metadata)

### Monitoring

The `/api/sat/status` endpoint includes `metadata_counts` with per-direction
breakdown of metadata-only vs parsed CFDIs. The sync status card on the SAT
config page shows a blue info panel when metadata-only CFDIs exist.

---

## FIEL certificate data conflicts

### Problem

When a user uploads a FIEL certificate, the RFC and razón social in the cert
may differ from what's stored in the issuer record.

### Behavior

After FIEL validation, `maybe_update_issuer_from_fiel()` runs:

1. If current RFC/razón social are **placeholders** (empty, "PENDIENTE",
   very short), they are auto-filled from the FIEL cert.
2. If current RFC is a **real RFC** (matches pattern `[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}`)
   but differs from the cert, a **conflict notification** is created:
   - Type: `fiel_rfc_conflict`
   - Severity: warning
   - Links to /portal/config/sat

### Resolution

The user should manually verify their RFC in the issuer settings and update
it if needed. The notification is idempotent (won't duplicate).

---

## Worker job types

| Job name | Table | Handler | Description |
|----------|-------|---------|-------------|
| `sat_sync_month` | `jobs` | `handle_sat_sync_month` | Sync a specific month |
| `sat_refresh_light` | `jobs` | `handle_sat_refresh_light` | Quick refresh for recent CFDIs |
| `sat_verify_credentials` | `jobs` | `handle_sat_verify_credentials` | Validate FIEL cert/key |
| `sat_xml_backfill` | `jobs` | `handle_sat_xml_backfill` | Download missing XMLs |
| `sat_verify_pending` | `jobs` | `handle_sat_verify_pending` | Check pending SAT requests |
| `sat_full_sync` | `jobs` | `handle_sat_full_sync` | Atomic 4-phase pipeline |

### Scheduler intervals

| Scheduler | Interval | Env var |
|-----------|----------|---------|
| `sat_refresh_light` | 5 min | `SAT_SCHEDULER_INTERVAL` |
| `sat_xml_backfill` | 6 hours | `SAT_BACKFILL_INTERVAL` |
| `sat_verify_pending` | 5 min | `SAT_VERIFY_INTERVAL` |
