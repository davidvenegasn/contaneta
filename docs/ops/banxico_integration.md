# Banxico DOF Exchange Rate Integration

## Overview

ContaNeta integrates with Banco de México's SIE API to fetch official DOF (Diario Oficial de la Federación) exchange rates. These are the legally valid rates for SAT Mexico tax compliance.

## Getting a Banxico Token

1. Go to https://www.banxico.org.mx/SieAPIRest/service/v1/token
2. Click "Registrarse" (or "Register")
3. Fill in your email — you'll receive a token instantly
4. The token is free and does not expire
5. Add to your `.env`:
   ```
   BANXICO_TOKEN=your_token_here
   ```

## Supported Currencies

| Currency | Banxico Series | Description |
|----------|---------------|-------------|
| USD | SF43718 | FIX para liquidar obligaciones en USD |
| EUR | SF46410 | Euro |
| GBP | SF60632 | Libra esterlina |
| JPY | SF46406 | Yen japonés |
| CAD | SF46408 | Dólar canadiense |
| CHF | SF46407 | Franco suizo |

## How It Works

### Rate Lookup (`get_rate`)

1. **Cache hit**: Check `dof_rates` table for exact date+currency match
2. **Banxico API**: If no cache hit, fetch from Banxico (7-day window to handle weekends)
3. **Nearest fallback**: If API fails, use the most recent cached rate within 30 days

### SAT Weekend/Holiday Rule

Banxico only publishes rates on Mexican business days. For weekends and holidays, the SAT rule is to use the rate from the last published business day. The client handles this automatically by fetching a 7-day window and picking the latest rate <= the requested date.

### Auto-Rate on Invoice Creation

When creating a foreign invoice with `tipo_cambio=0` (or negative), the system automatically attempts to fetch the DOF rate for the invoice date. If Banxico is unavailable, the original value is kept.

## Running the Backfill Script

The backfill script recalculates `tipo_cambio` and `monto_mxn` for all existing foreign invoices using real DOF rates.

### Dry Run (preview only)
```bash
PYTHONPATH=. .venv/bin/python scripts/backfill_foreign_invoices_rates.py
```

### Apply Changes
```bash
PYTHONPATH=. .venv/bin/python scripts/backfill_foreign_invoices_rates.py --apply
```

Output shows:
- `[UPDATE]` — invoice will be/was updated with new rate
- `[MISSING]` — no rate available for that date/currency
- Summary: total updates, missing rates, skipped (MXN invoices)

## Fallback Policy

| Scenario | Behavior |
|----------|----------|
| `BANXICO_TOKEN` not set | `get_rate()` returns `None`; manual rate required |
| Banxico API down | Falls back to nearest cached rate (30 days) |
| No cached rate available | Returns `None`; caller uses manual rate |
| Unsupported currency | Returns `None` |
| Weekend/holiday date | Uses last published business day rate |

## Adding More Currencies

Edit `BANXICO_SERIES` in `services/invoices/banxico_client.py`:

```python
BANXICO_SERIES = {
    "USD": "SF43718",
    "EUR": "SF46410",
    # Add new currency:
    "AUD": "SF46XXX",  # Find series ID at https://www.banxico.org.mx/SieAPIRest/
}
```

Find series IDs at: https://www.banxico.org.mx/SieAPIRest/service/v1/series

## Database

Exchange rates are stored in the `dof_rates` table (migration 046):

```sql
SELECT * FROM dof_rates WHERE currency = 'USD' ORDER BY date DESC LIMIT 10;
```

The table uses `UNIQUE(date, currency)` — duplicate inserts are silently ignored (`INSERT OR IGNORE`).
