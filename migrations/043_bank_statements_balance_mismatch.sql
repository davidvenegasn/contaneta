-- Migración 043: flag para discrepancia de saldo en estados de cuenta
-- has_balance_mismatch = 1 cuando opening_balance + sum(deposito) - sum(retiro) != closing_balance
ALTER TABLE bank_statements ADD COLUMN has_balance_mismatch INTEGER DEFAULT 0;
ALTER TABLE bank_statements ADD COLUMN computed_closing_balance REAL;
ALTER TABLE bank_statements ADD COLUMN balance_diff REAL;
