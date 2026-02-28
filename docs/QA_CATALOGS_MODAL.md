# QA Checklist — Catalogs + Quick Invoice + Modal Scroll

## Bootstrap Endpoint (`/api/quick-invoice/bootstrap`)
- [ ] 1. Response includes `catalogs` key with: `regimen_fiscal`, `uso_cfdi`, `forma_pago`, `metodo_pago`, `monedas`
- [ ] 2. Response includes `defaults.exchange_rate` = 1.0
- [ ] 3. All catalog arrays have `{key, label}` format

## Quick Invoice Modal (`/portal/home` → Factura rápida)
- [ ] 4. All dropdowns (Régimen, Uso CFDI, Forma de pago, Método, Moneda) populate from bootstrap — no extra HTTP calls
- [ ] 5. Moneda dropdown shows full currency list (MXN, USD, EUR, etc.)
- [ ] 6. Selecting non-MXN currency reveals "Tipo de cambio" input
- [ ] 7. Selecting MXN hides exchange rate field and resets to 1.0
- [ ] 8. After ProdServ search → selecting a result shows description below the input
- [ ] 9. Unit key shows description below input after selecting from datalist
- [ ] 10. Exchange rate value is sent in the timbrar payload

## Modal Scroll Lock
- [ ] 11. Opening any modal prevents body from scrolling (desktop + mobile)
- [ ] 12. Scrolling inside modal panel does NOT propagate to body
- [ ] 13. Modal header stays sticky at top when scrolling modal content
- [ ] 14. Modal footer (buttons) stays sticky at bottom when scrolling
- [ ] 15. Closing modal restores body scroll

## Regression
- [ ] 16. `/portal/create` (nueva factura completa) still loads catalogs independently — not affected
- [ ] 17. Quick invoice timbrar still works end-to-end
- [ ] 18. 17 tests pass (`pytest -q`)
