-- Migración 045: alias de cuenta propia detectada en movimiento
-- Almacena el nombre/referencia de la cuenta propia que matcheó (ej. "BBVA *1234")
ALTER TABLE bank_movements ADD COLUMN own_account_alias TEXT;
