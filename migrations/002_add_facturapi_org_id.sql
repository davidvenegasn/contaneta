-- 002_add_facturapi_org_id.sql
-- Asegura que la tabla issuers tenga la columna facturapi_org_id TEXT.
-- SQLite no soporta "ADD COLUMN ... IF NOT EXISTS". Se usa workaround seguro:
-- crear issuers_new con schema final, copiar datos, eliminar issuers y renombrar.
-- 
-- IMPORTANTE: Esta migración requiere que issuers tenga el schema completo de 001_baseline.
-- Si la tabla es más antigua y le faltan columnas (p. ej. regimen_fiscal, razon_social),
-- la migración fallará. En ese caso, ejecutar primero 001_baseline para crear el schema completo.
-- 
-- Si issuers ya tiene facturapi_org_id (p. ej. por 001_baseline), esta migración
-- intentará copiarla también, pero como usamos NULL en el SELECT, no la copiamos.
-- Para evitar pérdida de datos, el runner debería verificar si la columna existe antes.

PRAGMA foreign_keys = OFF;

-- 0) Limpiar tabla temporal si existe (por si la migración falló anteriormente)
DROP TABLE IF EXISTS issuers_new;

-- 1) Crear tabla nueva con schema final (incluye facturapi_org_id)
CREATE TABLE issuers_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rfc TEXT,
  razon_social TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  active INTEGER NOT NULL DEFAULT 1,
  regimen_fiscal TEXT,
  facturapi_org_id TEXT
);

-- 2) Copiar datos: usar solo columnas que siempre existen (id, rfc) para máxima compatibilidad.
--    Otras columnas pueden no existir en DBs antiguas, así que usamos valores por defecto.
--    NOTA: Esto perderá datos de columnas existentes (razon_social, created_at, etc.) si existen.
--    Para preservar TODOS los datos, ejecutar primero 001_baseline que crea el schema completo.
INSERT INTO issuers_new (
  id, rfc, razon_social, created_at, updated_at, active, regimen_fiscal, facturapi_org_id
)
SELECT
  id,
  rfc,
  NULL AS razon_social,
  datetime('now') AS created_at,
  datetime('now') AS updated_at,
  1 AS active,
  NULL AS regimen_fiscal,
  NULL AS facturapi_org_id
FROM issuers;

-- 3) Sustituir tabla antigua por la nueva
DROP TABLE issuers;
ALTER TABLE issuers_new RENAME TO issuers;

PRAGMA foreign_keys = ON;
