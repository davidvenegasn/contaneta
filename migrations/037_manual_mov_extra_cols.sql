-- Add forma_pago and contraparte columns to manual_movements
ALTER TABLE manual_movements ADD COLUMN forma_pago TEXT;
ALTER TABLE manual_movements ADD COLUMN contraparte TEXT;
