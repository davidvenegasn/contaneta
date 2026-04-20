-- 036: Invoice cancellation support
-- cancel_status: null | 'pending' | 'accepted' | 'rejected'
-- cancel_motive: '01' (con reemplazo) | '02' (sin reemplazo) | '03' (no se realizó) | '04' (factura global)
-- replacement_uuid: UUID of the invoice that replaces this one (motive 01, set on original)
-- replaces_uuid: UUID of the invoice this one replaces (set on the replacement)
-- cancelled_at: ISO timestamp of cancellation

ALTER TABLE invoices ADD COLUMN cancel_status TEXT;
ALTER TABLE invoices ADD COLUMN cancel_motive TEXT;
ALTER TABLE invoices ADD COLUMN replacement_uuid TEXT;
ALTER TABLE invoices ADD COLUMN replaces_uuid TEXT;
ALTER TABLE invoices ADD COLUMN cancelled_at TEXT;
