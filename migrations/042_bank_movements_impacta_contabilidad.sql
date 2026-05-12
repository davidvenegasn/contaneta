-- Migración 042: agregar columna impacta_contabilidad a bank_movements
-- Indica si el movimiento impacta los totales contables (excluye financieros, traspasos propios)
-- DEFAULT 1 = todos los movimientos existentes se consideran contables (conservative)
ALTER TABLE bank_movements ADD COLUMN impacta_contabilidad INTEGER DEFAULT 1;
