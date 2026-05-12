-- Migración 044: audit trail para ediciones de movimientos bancarios
CREATE TABLE IF NOT EXISTS bank_movement_edits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issuer_id INTEGER NOT NULL,
    movement_id INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    edited_by INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (movement_id) REFERENCES bank_movements(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_bme_movement ON bank_movement_edits(movement_id);
CREATE INDEX IF NOT EXISTS idx_bme_issuer ON bank_movement_edits(issuer_id);
