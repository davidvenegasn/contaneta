-- 072: Constancia de Situación Fiscal — columns on issuers
ALTER TABLE issuers ADD COLUMN constancia_pdf_path TEXT;
ALTER TABLE issuers ADD COLUMN constancia_uploaded_at TEXT;
ALTER TABLE issuers ADD COLUMN constancia_extracted_json TEXT;
