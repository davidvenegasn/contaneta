-- 006_add_users_name.sql
-- Agrega columna name a users (nombre para mostrar; se rellena desde confirmar-perfil o OAuth).
-- La migración se aplica con lógica Python (idempotente) en migrations_runner.

-- ALTER TABLE users ADD COLUMN name TEXT;
