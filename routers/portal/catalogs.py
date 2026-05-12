"""Portal catalogs routes."""
import logging

from fastapi import Body, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from database import db, table_exists
from routers.deps import get_portal_issuer
from routers.portal._helpers import (
    MAX_LIST_OFFSET,
    _db_row_to_dict,
    render_portal,
)
from services.action_log import log_action
from services.auth import rate_limit as rate_limit_service
from services.invoices.catalog_from_cfdi import backfill_catalog_from_existing_cfdi
from services.sat.sat_sync import get_month_totals, get_sat_sync_status

logger = logging.getLogger(__name__)

_get_month_totals = get_month_totals
_get_sat_sync_status = get_sat_sync_status


def register_catalogs_routes(router, templates):
    """Register Catalogs routes on the portal router."""

    def _render_portal(request, **kwargs):
        return render_portal(templates, request, **kwargs)

    @router.get("/contactos", response_class=RedirectResponse)
    def portal_contactos_hub(tab: str = Query("clientes")):
        """Redirect legacy /contactos to /catalogos."""
        new_tab = "proveedores" if tab == "proveedores" else "clientes"
        return RedirectResponse(url=f"/portal/catalogos?tab={new_tab}", status_code=302)

    # ---------- Catálogos hub (replaces separate Clientes + Productos + Proveedores links) ----------
    @router.get("/catalogos", response_class=HTMLResponse)
    def portal_catalogos_hub(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        tab: str = Query("clientes", description="clientes|productos|proveedores"),
        q: str = Query(""),
        page: int = Query(1, ge=1),
        per_page: int = Query(200, ge=1, le=500),
    ):
        """Hub Catálogos: tabs Clientes / Productos / Proveedores."""
        try:
            if tab not in ("clientes", "productos", "proveedores"):
                tab = "clientes"
            issuer_id = int(issuer.get("id") or 0)
            rows = []
            total = 0
            pages = 0
            query = (q or "").strip()
            max_page = (MAX_LIST_OFFSET // max(1, int(per_page))) + 1
            if page > max_page:
                page = max_page

            if tab == "clientes" and issuer_id > 0:
                conn = db()
                try:
                    if table_exists(conn, "clients"):
                        if query:
                            like = f"%{query}%"
                            total_row = conn.execute(
                                "SELECT COUNT(*) AS c FROM clients WHERE issuer_id = ? AND (rfc LIKE ? OR COALESCE(name,'') LIKE ?)",
                                (issuer_id, like, like),
                            ).fetchone()
                            total = int(total_row.get("c") or total_row.get("n") or 0) if total_row else 0
                            offset = (page - 1) * per_page
                            rows = conn.execute(
                                """
                                SELECT id, rfc, name, cp, regimen_fiscal, uso_cfdi_default, email, phone, last_seen_at
                                FROM clients
                                WHERE issuer_id = ? AND (rfc LIKE ? OR COALESCE(name,'') LIKE ?)
                                ORDER BY COALESCE(last_seen_at, created_at) DESC
                                LIMIT ? OFFSET ?
                                """,
                                (issuer_id, like, like, per_page, offset),
                            ).fetchall()
                        else:
                            total_row = conn.execute(
                                "SELECT COUNT(*) AS c FROM clients WHERE issuer_id = ?", (issuer_id,)
                            ).fetchone()
                            total = int(total_row.get("c") or total_row.get("n") or 0) if total_row else 0
                            offset = (page - 1) * per_page
                            rows = conn.execute(
                                """
                                SELECT id, rfc, name, cp, regimen_fiscal, uso_cfdi_default, email, phone, last_seen_at
                                FROM clients
                                WHERE issuer_id = ?
                                ORDER BY COALESCE(last_seen_at, created_at) DESC
                                LIMIT ? OFFSET ?
                                """,
                                (issuer_id, per_page, offset),
                            ).fetchall()
                        rows = [_db_row_to_dict(r) for r in rows]
                        pages = (total + per_page - 1) // per_page if total > 0 else 0
                finally:
                    conn.close()
            elif tab == "productos" and issuer_id > 0:
                conn = db()
                try:
                    if query:
                        like = f"%{query}%"
                        total_row = conn.execute(
                            "SELECT COUNT(*) AS c FROM products WHERE issuer_id = ? AND (COALESCE(name,'') LIKE ? OR COALESCE(clave_prod_serv,'') LIKE ?)",
                            (issuer_id, like, like),
                        ).fetchone()
                        total = int(total_row.get("c") or total_row.get("n") or 0) if total_row else 0
                        offset = (page - 1) * per_page
                        rows = conn.execute(
                            """
                            SELECT id, name, clave_prod_serv, clave_unidad, unidad,
                                   default_unit_price, default_currency, active, updated_at
                            FROM products
                            WHERE issuer_id = ?
                              AND (COALESCE(name,'') LIKE ? OR COALESCE(clave_prod_serv,'') LIKE ?)
                            ORDER BY active DESC, updated_at DESC
                            LIMIT ? OFFSET ?
                            """,
                            (issuer_id, like, like, per_page, offset),
                        ).fetchall()
                    else:
                        total_row = conn.execute(
                            "SELECT COUNT(*) AS c FROM products WHERE issuer_id = ?", (issuer_id,)
                        ).fetchone()
                        total = int(total_row.get("c") or total_row.get("n") or 0) if total_row else 0
                        offset = (page - 1) * per_page
                        rows = conn.execute(
                            """
                            SELECT id, name, clave_prod_serv, clave_unidad, unidad,
                                   default_unit_price, default_currency, active, updated_at
                            FROM products
                            WHERE issuer_id = ?
                            ORDER BY active DESC, updated_at DESC
                            LIMIT ? OFFSET ?
                            """,
                            (issuer_id, per_page, offset),
                        ).fetchall()
                    rows = [dict(r) for r in rows] if rows else []
                    pages = (total + per_page - 1) // per_page if total > 0 else 0
                finally:
                    conn.close()
            # proveedores tab: data is loaded client-side (API), no server rows needed

            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_catalogos.html",
                active_page="catalogos_hub",
                title="Catálogos",
                extra={
                    "active_tab": tab,
                    "rows": rows,
                    "q": query,
                    "total": total,
                    "page": page,
                    "per_page": per_page,
                    "pages": pages,
                    "hub_base": "/portal/catalogos",
                },
            )
        except Exception:
            logger.exception("portal: error renderizando /portal/catalogos tab=%s", tab)
            raise

    @router.get("/clients", response_class=RedirectResponse)
    def portal_clients_redirect():
        """Redirect legacy /clients to /catalogos?tab=clientes."""
        return RedirectResponse(url="/portal/catalogos?tab=clientes", status_code=302)

    @router.get("/providers", response_class=RedirectResponse)
    def portal_providers_redirect():
        """Redirect legacy /providers to /catalogos?tab=proveedores."""
        return RedirectResponse(url="/portal/catalogos?tab=proveedores", status_code=302)

    @router.get("/products", response_class=RedirectResponse)
    def portal_products_redirect():
        """Redirect legacy /products to /catalogos?tab=productos."""
        return RedirectResponse(url="/portal/catalogos?tab=productos", status_code=302)

    @router.get("/products/suggestions", response_class=HTMLResponse)
    def portal_products_suggestions(request: Request, issuer: dict = Depends(get_portal_issuer), q: str = Query("")):
        try:
            issuer_id = int(issuer.get("id") or 0)
            query = (q or "").strip()
            rows = []
            if issuer_id > 0:
                conn = db()
                try:
                    if query:
                        like = f"%{query}%"
                        rows = conn.execute(
                            """
                            SELECT id, clave_prod_serv, raw_description, clave_unidad, unidad,
                                   unit_price_hint, currency, times_seen, last_seen_at
                            FROM product_observations
                            WHERE issuer_id = ?
                              AND (COALESCE(raw_description,'') LIKE ? OR COALESCE(clave_prod_serv,'') LIKE ?)
                            ORDER BY times_seen DESC, last_seen_at DESC
                            LIMIT 500
                            """,
                            (issuer_id, like, like),
                        ).fetchall()
                    else:
                        rows = conn.execute(
                            """
                            SELECT id, clave_prod_serv, raw_description, clave_unidad, unidad,
                                   unit_price_hint, currency, times_seen, last_seen_at
                            FROM product_observations
                            WHERE issuer_id = ?
                            ORDER BY times_seen DESC, last_seen_at DESC
                            LIMIT 500
                            """,
                            (issuer_id,),
                        ).fetchall()
                finally:
                    conn.close()
            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_product_suggestions.html",
                active_page="product_suggestions",
                title="Productos sugeridos",
                extra={"rows": [dict(r) for r in rows] if rows else [], "q": query},
            )
        except Exception:
            logger.exception("portal: error renderizando /portal/products/suggestions")
            raise

    @router.post("/products/suggestions/{observation_id}/convert", response_class=JSONResponse)
    def portal_products_suggestions_convert(
        request: Request,
        observation_id: int,
        payload: dict = Body(default_factory=dict),
        issuer: dict = Depends(get_portal_issuer),
    ):
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        try:
            obs_id = int(observation_id)
        except Exception:
            raise HTTPException(status_code=400, detail="ID inválido")

        name_override = (payload.get("name") if isinstance(payload, dict) else "") or ""
        name_override = str(name_override).strip()

        conn = db()
        try:
            obs = conn.execute(
                """
                SELECT id, clave_prod_serv, clave_unidad, unidad, raw_description, unit_price_hint, currency
                FROM product_observations
                WHERE issuer_id = ? AND id = ?
                LIMIT 1
                """,
                (issuer_id, obs_id),
            ).fetchone()
            if not obs:
                raise HTTPException(status_code=404, detail="Sugerencia no encontrada")

            name = name_override or (obs["raw_description"] or "").strip()
            if not name:
                raise HTTPException(status_code=400, detail="Nombre del producto es obligatorio")

            cps = (obs["clave_prod_serv"] or "").strip() or None
            cu = (obs["clave_unidad"] or "").strip() or None
            unidad = (obs["unidad"] or "").strip() or None
            price = obs["unit_price_hint"]
            currency = (obs["currency"] or "").strip().upper() or None

            conn.execute(
                """
                INSERT INTO products (
                  issuer_id, name, clave_prod_serv, clave_unidad, unidad,
                  default_unit_price, default_currency, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, datetime('now'), datetime('now'))
                ON CONFLICT(issuer_id, name, clave_prod_serv, clave_unidad) DO UPDATE SET
                  unidad = COALESCE(excluded.unidad, products.unidad),
                  default_unit_price = COALESCE(excluded.default_unit_price, products.default_unit_price),
                  default_currency = COALESCE(excluded.default_currency, products.default_currency),
                  active = 1,
                  updated_at = datetime('now')
                """,
                (issuer_id, name, cps, cu, unidad, price, currency),
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT id FROM products
                WHERE issuer_id = ? AND name = ? AND COALESCE(clave_prod_serv,'') = COALESCE(?, '')
                  AND COALESCE(clave_unidad,'') = COALESCE(?, '')
                ORDER BY id DESC LIMIT 1
                """,
                (issuer_id, name, cps, cu),
            ).fetchone()
            prod_id = int(row["id"]) if row else None
        finally:
            conn.close()

        log_action(request, "product_converted_from_observation", issuer_id=issuer_id, entity_id=str(obs_id))
        return JSONResponse({"ok": True, "product_id": prod_id})

    @router.post("/products/save", response_class=JSONResponse)
    def portal_products_save(
        request: Request,
        payload: dict = Body(...),
        issuer: dict = Depends(get_portal_issuer),
    ):
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Payload inválido")

        prod_id = payload.get("id")
        name = str(payload.get("name") or "").strip()
        clave_prod_serv = str(payload.get("clave_prod_serv") or "").strip() or None
        clave_unidad = str(payload.get("clave_unidad") or "").strip() or None
        unidad = str(payload.get("unidad") or "").strip() or None
        default_currency = str(payload.get("default_currency") or "").strip().upper() or None
        active = 1 if str(payload.get("active") or "1").strip() not in ("0", "false", "False") else 0
        default_unit_price = payload.get("default_unit_price")
        try:
            default_unit_price = float(default_unit_price) if default_unit_price not in (None, "", "null") else None
        except Exception:
            raise HTTPException(status_code=400, detail="Precio inválido")

        if not name:
            raise HTTPException(status_code=400, detail="Nombre es obligatorio")

        conn = db()
        try:
            if prod_id is not None and str(prod_id).strip():
                pid = int(prod_id)
                cur = conn.execute(
                    """
                    UPDATE products SET
                      name = ?,
                      clave_prod_serv = ?,
                      clave_unidad = ?,
                      unidad = ?,
                      default_unit_price = ?,
                      default_currency = ?,
                      active = ?,
                      updated_at = datetime('now')
                    WHERE issuer_id = ? AND id = ?
                    """,
                    (name, clave_prod_serv, clave_unidad, unidad, default_unit_price, default_currency, active, issuer_id, pid),
                )
                if cur.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Producto no encontrado")
                conn.commit()
                return JSONResponse({"ok": True, "id": pid})

            conn.execute(
                """
                INSERT INTO products (
                  issuer_id, name, clave_prod_serv, clave_unidad, unidad,
                  default_unit_price, default_currency, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(issuer_id, name, clave_prod_serv, clave_unidad) DO UPDATE SET
                  unidad = COALESCE(excluded.unidad, products.unidad),
                  default_unit_price = COALESCE(excluded.default_unit_price, products.default_unit_price),
                  default_currency = COALESCE(excluded.default_currency, products.default_currency),
                  active = excluded.active,
                  updated_at = datetime('now')
                """,
                (issuer_id, name, clave_prod_serv, clave_unidad, unidad, default_unit_price, default_currency, active),
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT id FROM products
                WHERE issuer_id = ? AND name = ? AND COALESCE(clave_prod_serv,'') = COALESCE(?, '')
                  AND COALESCE(clave_unidad,'') = COALESCE(?, '')
                ORDER BY id DESC LIMIT 1
                """,
                (issuer_id, name, clave_prod_serv, clave_unidad),
            ).fetchone()
            return JSONResponse({"ok": True, "id": int(row["id"]) if row else None})
        finally:
            conn.close()

    @router.post("/products/{product_id}/toggle", response_class=JSONResponse)
    def portal_products_toggle(request: Request, product_id: int, issuer: dict = Depends(get_portal_issuer)):
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        pid = int(product_id)
        conn = db()
        try:
            row = conn.execute(
                "SELECT active FROM products WHERE issuer_id = ? AND id = ? LIMIT 1",
                (issuer_id, pid),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Producto no encontrado")
            new_val = 0 if int(row["active"] or 0) == 1 else 1
            conn.execute(
                "UPDATE products SET active = ?, updated_at = datetime('now') WHERE issuer_id = ? AND id = ?",
                (new_val, issuer_id, pid),
            )
            conn.commit()
        finally:
            conn.close()
        return JSONResponse({"ok": True, "active": new_val})

    @router.post("/products/{product_id}/delete", response_class=JSONResponse)
    def portal_products_delete(request: Request, product_id: int, issuer: dict = Depends(get_portal_issuer)):
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        pid = int(product_id)
        conn = db()
        try:
            cur = conn.execute(
                "DELETE FROM products WHERE issuer_id = ? AND id = ?",
                (issuer_id, pid),
            )
            conn.commit()
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Producto no encontrado")
        finally:
            conn.close()
        return JSONResponse({"ok": True})

    @router.post("/clients/save", response_class=JSONResponse)
    def portal_clients_save(request: Request, payload: dict = Body(...), issuer: dict = Depends(get_portal_issuer)):
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Payload inválido")

        cid = payload.get("id")
        name = str(payload.get("name") or "").strip() or None
        cp = str(payload.get("cp") or "").strip() or None
        regimen = str(payload.get("regimen_fiscal") or "").strip() or None
        uso = str(payload.get("uso_cfdi_default") or "").strip().upper() or None
        email = str(payload.get("email") or "").strip() or None
        phone = str(payload.get("phone") or "").strip() or None

        if cid is None or not str(cid).strip():
            raise HTTPException(status_code=400, detail="ID requerido")
        client_id = int(cid)

        conn = db()
        try:
            cur = conn.execute(
                """
                UPDATE clients SET
                  name = COALESCE(?, name),
                  cp = COALESCE(?, cp),
                  regimen_fiscal = COALESCE(?, regimen_fiscal),
                  uso_cfdi_default = COALESCE(?, uso_cfdi_default),
                  email = COALESCE(?, email),
                  phone = COALESCE(?, phone),
                  updated_at = datetime('now')
                WHERE issuer_id = ? AND id = ?
                """,
                (name, cp, regimen, uso, email, phone, issuer_id, client_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Cliente no encontrado")
            conn.commit()
        finally:
            conn.close()

    @router.post("/clients/{client_id}/delete", response_class=JSONResponse)
    def portal_clients_delete(request: Request, client_id: int, issuer: dict = Depends(get_portal_issuer)):
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        cid = int(client_id)
        conn = db()
        try:
            cur = conn.execute(
                "DELETE FROM clients WHERE issuer_id = ? AND id = ?",
                (issuer_id, cid),
            )
            conn.commit()
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Cliente no encontrado")
        finally:
            conn.close()
        return JSONResponse({"ok": True})
        return JSONResponse({"ok": True, "id": client_id})

    @router.post("/catalog/backfill", response_class=JSONResponse)
    def portal_catalog_backfill(
        request: Request,
        payload: dict = Body(default_factory=dict),
        issuer: dict = Depends(get_portal_issuer),
    ):
        """
        Dispara backfill de catálogo sugerido (clients + product_observations) desde CFDI emitidos ya guardados.
        Responde JSON con métricas. Multi-issuer: siempre filtra por issuer_id actual.
        """
        if rate_limit_service.is_rate_limited(request, "catalog_backfill"):
            return JSONResponse({"ok": False, "detail": "Demasiados intentos. Espera un minuto."}, status_code=429)
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesión inválida")

        limit = payload.get("limit") if isinstance(payload, dict) else None
        since = payload.get("since") if isinstance(payload, dict) else None
        try:
            result = backfill_catalog_from_existing_cfdi(
                issuer_id,
                limit=int(limit) if limit is not None and str(limit).strip() else None,
                since=str(since).strip() if since is not None and str(since).strip() else None,
            )
        except Exception as e:
            logger.exception("portal catalog backfill: issuer=%s", issuer_id)
            raise HTTPException(status_code=500, detail="No se pudo ejecutar el backfill. Revisa que existan XML emitidos y que las migraciones estén aplicadas.")

        return JSONResponse(
            {
                "ok": True,
                "processed": result.processed,
                "clients_upserted": result.clients_upserted,
                "observations_upserted": result.observations_upserted,
                "errors_count": result.errors_count,
                "errors_sample": (result.errors or [])[:10],
            }
        )

