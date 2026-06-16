-- PPD payment state tracking: one row per parcialidad received.
-- Stores the saldo before/after each payment so the next REP can pick up
-- ImpSaldoAnt and NumParcialidad without recomputing from history.
CREATE TABLE IF NOT EXISTS invoice_payments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    issuer_id           INTEGER NOT NULL,
    invoice_id          INTEGER NOT NULL REFERENCES invoices(id),
    rep_invoice_id      INTEGER REFERENCES invoices(id),   -- FK to the CFDI P emitted
    rep_uuid            TEXT,                               -- UUID of the CFDI P
    parcialidad         INTEGER NOT NULL DEFAULT 1,        -- sequential 1, 2, 3 …
    fecha_pago          TEXT NOT NULL,                     -- ISO date YYYY-MM-DD
    forma_pago          TEXT NOT NULL,                     -- SAT code: 03, 02, 04…
    moneda_pago         TEXT NOT NULL DEFAULT 'MXN',
    tipo_cambio_pago    TEXT,                              -- stored as TEXT to preserve precision
    monto_pagado        REAL NOT NULL,                     -- in moneda_pago
    importe_abonado     REAL NOT NULL,                     -- in moneda of original invoice (MonedaDR)
    saldo_anterior      REAL NOT NULL,                     -- ImpSaldoAnt in MonedaDR
    saldo_insoluto      REAL NOT NULL,                     -- ImpSaldoAnt - importe_abonado
    num_operacion       TEXT,                              -- bank reference / folio
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_invoice_payments_invoice  ON invoice_payments(invoice_id);
CREATE INDEX IF NOT EXISTS idx_invoice_payments_issuer   ON invoice_payments(issuer_id);
CREATE INDEX IF NOT EXISTS idx_invoice_payments_parcial  ON invoice_payments(invoice_id, parcialidad);
