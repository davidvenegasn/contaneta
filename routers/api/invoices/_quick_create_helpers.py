"""Helper functions for quick invoice creation — product resolution, rate parsing, item building."""
from fastapi import HTTPException

from database import db, db_rows, table_exists
from validators import validate_product


def resolve_product(issuer_id: int, pid: int) -> dict:
    """Resolve a product from issuer_products or legacy products table.

    Raises:
        HTTPException: If product not found.
    """
    rows = db_rows(
        "SELECT id, description, product_key, unit_key, unit_price, iva_rate FROM issuer_products WHERE issuer_id = ? AND id = ? LIMIT 1",
        (issuer_id, pid),
    )
    if rows:
        return rows[0]
    _conn = db()
    try:
        if table_exists(_conn, "products"):
            row = _conn.execute(
                "SELECT id, name, clave_prod_serv, clave_unidad, default_unit_price FROM products WHERE issuer_id = ? AND id = ? LIMIT 1",
                (issuer_id, pid),
            ).fetchone()
            if row:
                row = dict(row)
                return {
                    "id": row["id"],
                    "description": row.get("name") or "",
                    "product_key": row.get("clave_prod_serv") or "",
                    "unit_key": row.get("clave_unidad") or "E48",
                    "unit_price": float(row.get("default_unit_price") or 0),
                    "iva_rate": 0.16,
                }
    finally:
        _conn.close()
    raise HTTPException(status_code=404, detail=f"Producto no encontrado: {pid}")


def parse_iva_rate(val, default_val: float) -> tuple[float, bool]:
    """Parse IVA rate, supporting 'EXENTO' for exempt items.

    Returns:
        Tuple of (iva_rate, iva_exempt).
    """
    if val is None or val == "":
        return (max(0.0, min(1.0, float(default_val))), False)
    if isinstance(val, str) and val.strip().upper() == "EXENTO":
        return (0.0, True)
    try:
        n = float(val)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="IVA rate invalido.")
    n = max(0.0, min(1.0, n))
    return (n, False)


def parse_rate(payload: dict, name: str, default: float = 0.0) -> float:
    """Parse a rate value from payload, clamped to [0, 1]."""
    v = payload.get(name)
    if v is None or v == "":
        return default
    try:
        n = float(v)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{name} invalido.")
    return max(0.0, min(1.0, n))


def build_invoice_items(
    issuer_id: int,
    payload: dict,
    items_in: list | None,
    product_id: int | None,
    quantity: float | None,
    unit_price_override: float | None,
    isr_ret_rate: float,
    iva_ret_rate: float,
) -> tuple[list[dict], list[dict]]:
    """Build Facturapi items and metadata from payload.

    Returns:
        Tuple of (items_fact, items_meta).
    """
    items_fact = []
    items_meta = []
    has_items = isinstance(items_in, list) and len(items_in) > 0

    if has_items:
        for it in items_in:
            if not isinstance(it, dict):
                raise HTTPException(status_code=400, detail="items invalidos.")
            pid = it.get("product_id")
            if not pid:
                raise HTTPException(status_code=400, detail="Cada item requiere product_id.")
            try:
                pid = int(pid)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="product_id invalido en items.")
            qty = float(it.get("quantity", 1))
            if qty <= 0 or qty > 999999:
                raise HTTPException(status_code=400, detail="Cantidad invalida en items.")
            base_p = resolve_product(issuer_id, pid)
            description = (it.get("description") or base_p.get("description") or "").strip() or (base_p.get("description") or "").strip()
            product_key = (it.get("product_key") or base_p.get("product_key") or "").strip() or "84111500"
            unit_key = (it.get("unit_key") or base_p.get("unit_key") or "").strip() or "E48"
            up_override = it.get("unit_price")
            if up_override is not None and up_override != "":
                try:
                    up_override = float(up_override)
                    if up_override < 0:
                        raise HTTPException(status_code=400, detail="Precio unitario no puede ser negativo.")
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail="Precio unitario invalido.")
            unit_price = float(up_override if up_override is not None and up_override != "" else (base_p.get("unit_price") or 0))
            iva_rate, iva_exempt = parse_iva_rate(it.get("iva_rate"), float(base_p.get("iva_rate") or 0.16))

            prod_errors = validate_product(description, product_key, unit_key, unit_price)
            if prod_errors:
                raise HTTPException(status_code=400, detail="; ".join(prod_errors))

            _append_item(items_fact, items_meta, qty, description, product_key, unit_key,
                         unit_price, iva_rate, iva_exempt, isr_ret_rate, iva_ret_rate)
    else:
        p = resolve_product(issuer_id, int(product_id))
        description = (payload.get("description") or p.get("description") or "").strip() or (p.get("description") or "").strip()
        product_key = (payload.get("product_key") or p.get("product_key") or "").strip() or "84111500"
        unit_key = (payload.get("unit_key") or p.get("unit_key") or "").strip() or "E48"
        unit_price = float(unit_price_override if unit_price_override is not None else (p.get("unit_price") or 0))
        iva_rate, iva_exempt = parse_iva_rate(payload.get("iva_rate"), float(p.get("iva_rate") or 0.16))

        prod_errors = validate_product(description, product_key, unit_key, unit_price)
        if prod_errors:
            raise HTTPException(status_code=400, detail="; ".join(prod_errors))

        _append_item(items_fact, items_meta, quantity, description, product_key, unit_key,
                     unit_price, iva_rate, iva_exempt, isr_ret_rate, iva_ret_rate)

    return items_fact, items_meta


def _append_item(items_fact, items_meta, qty, description, product_key, unit_key,
                 unit_price, iva_rate, iva_exempt, isr_ret_rate, iva_ret_rate):
    """Append a single item to both Facturapi and metadata lists."""
    price_to_send = unit_price * (1.0 + iva_rate) if iva_rate else unit_price
    taxes = []
    if not iva_exempt:
        taxes.append({"type": "IVA", "rate": iva_rate})
    if isr_ret_rate > 0:
        taxes.append({"type": "ISR", "rate": isr_ret_rate, "withholding": True})
    if iva_ret_rate > 0:
        taxes.append({"type": "IVA", "rate": iva_ret_rate, "withholding": True})
    items_fact.append(
        {
            "quantity": qty,
            "discount": 0.0,
            "product": {
                "description": description,
                "product_key": product_key,
                "price": round(price_to_send, 2),
                "tax_included": True,
                "taxes": taxes,
                "unit_key": unit_key,
            },
        }
    )
    items_meta.append(
        {
            "quantity": qty,
            "description": description,
            "product_key": product_key,
            "unit_key": unit_key,
            "unit_price": unit_price,
            "iva_rate": iva_rate,
            "price_to_send": round(price_to_send, 2),
        }
    )
