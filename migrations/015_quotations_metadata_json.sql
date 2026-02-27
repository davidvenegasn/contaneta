-- Snapshot del contenido de la cotización para que el PDF sea consistente
-- aunque se editen productos o datos después.
ALTER TABLE quotations ADD COLUMN metadata_json TEXT;
