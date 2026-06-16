-- 070: SAT Lista 69-B (EFOS) cache table
CREATE TABLE IF NOT EXISTS sat_lista_69b (
  rfc TEXT PRIMARY KEY,
  nombre TEXT,
  situacion TEXT,             -- Definitivo, Presunto, Desvirtuado, Sentencia Favorable
  refreshed_at TEXT NOT NULL DEFAULT (datetime('now'))
);
