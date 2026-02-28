-- 029_month_close_enhance.sql
-- Enhance month_close_status with status enum, checklist_json, and pdf paths.

ALTER TABLE month_close_status ADD COLUMN status TEXT NOT NULL DEFAULT 'draft';
-- status: draft | submitted | confirmed

ALTER TABLE month_close_status ADD COLUMN checklist_json TEXT;
-- JSON object with check items: { "sat_sync": true, "issued_ok": false, ... }

ALTER TABLE month_close_status ADD COLUMN acuse_pdf_path TEXT;
ALTER TABLE month_close_status ADD COLUMN opinion_pdf_path TEXT;
