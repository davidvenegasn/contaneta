-- 008_users_active.sql
-- Asegura columna active en users (default 1) para desactivar cuentas sin borrarlas.
-- No guardar nunca contraseña en texto plano; el hash ya está en password_hash (bcrypt).

PRAGMA foreign_keys = ON;

-- users.active: 1 = activo, 0 = desactivado (no puede hacer login)
-- La migración se aplica con lógica Python (idempotente) en migrations_runner (_safe_add_column).
