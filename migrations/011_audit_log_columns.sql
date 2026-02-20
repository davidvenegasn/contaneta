-- 011_audit_log_columns.sql
-- Añade columnas a audit_log: entity, entity_id, meta_json, ip, user_agent.
-- Aplicada con lógica Python idempotente en migrations_runner (_apply_011_audit_log_columns).

-- (No SQL ejecutado aquí; el runner aplica _safe_add_column para cada columna.)
