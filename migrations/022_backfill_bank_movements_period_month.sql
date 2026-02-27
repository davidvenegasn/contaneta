-- Backfill period_month from each movement's fecha (so each row is in the correct month).
-- Fixes movements that were saved with statement period (e.g. Saldo anterior 2025-12-31 made all go to Dec).
-- Only when fecha is in YYYY-MM-DD format.
UPDATE bank_movements
SET period_month = substr(trim(fecha), 1, 7)
WHERE fecha IS NOT NULL
  AND trim(fecha) != ''
  AND length(trim(fecha)) >= 7
  AND substr(trim(fecha), 1, 4) GLOB '[0-9][0-9][0-9][0-9]'
  AND substr(trim(fecha), 5, 1) = '-'
  AND substr(trim(fecha), 6, 2) GLOB '[0-9][0-9]';
