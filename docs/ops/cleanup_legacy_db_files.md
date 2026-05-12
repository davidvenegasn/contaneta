# Legacy DB Recovery Files — Cleanup Guide

**Date:** 2026-05-12

## Files

These files in the repo root are leftovers from a DB recovery event (Feb 17, 2026):

| File | Size | Purpose |
|------|------|---------|
| `invoicing.db.bad` | 28 KB | Corrupted DB snapshot |
| `invoicing.db.bak` | 161 KB | Pre-recovery backup |
| `invoicing.db.lost_and_found_backup` | 28 KB | Recovery attempt |
| `invoicing.db.lost_and_found_backup-shm` | 32 KB | WAL shared memory (recovery) |
| `invoicing.db.lost_and_found_backup-wal` | 0 B | WAL file (recovery) |
| `invoicing.db-shm.bad` | 32 KB | Corrupted SHM |
| `invoicing.db-shm.bak` | 32 KB | SHM backup |
| `invoicing.db-wal.bad` | 0 B | Corrupted WAL |
| `invoicing.db-wal.bak` | 1 MB | WAL backup |
| `fixed.db` | 0 B | Empty recovery artifact |
| `dump_recover.sql` | 45 KB | SQL dump for recovery |

## When Safe to Delete

You can delete these files from your local filesystem when ALL of these are true:

1. `invoicing.db` is healthy: `sqlite3 invoicing.db "PRAGMA integrity_check;"` returns "ok"
2. A recent backup exists and has been verified: `bash scripts/verify_backup.sh <backup_file>`
3. The app is running and passing health checks: `curl http://localhost:8000/health`

```bash
# Delete all recovery artifacts (after verifying above conditions)
rm -f invoicing.db.bad invoicing.db.bak invoicing.db.lost_and_found_backup*
rm -f invoicing.db-shm.bad invoicing.db-shm.bak invoicing.db-wal.bad invoicing.db-wal.bak
rm -f fixed.db dump_recover.sql
```

## Git Status

These files have been removed from git tracking (`.gitignore` updated). They will not appear in `git status` even if they exist on disk.
