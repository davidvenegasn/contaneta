-- Track quotation-to-invoice conversion
ALTER TABLE quotations ADD COLUMN converted_invoice_id INTEGER;
ALTER TABLE quotations ADD COLUMN converted_at TEXT;
