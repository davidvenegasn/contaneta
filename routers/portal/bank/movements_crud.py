"""Bank movement CRUD routes — match confirm/reject, update, edits, delete-all."""
import logging

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from database import db, table_exists
from routers.deps import get_portal_issuer
from routers.portal._helpers import _db_row_to_dict
from services.bank.bank_cfdi_matching import confirm_match as match_confirm
from services.bank.bank_cfdi_matching import reject_match as match_reject

logger = logging.getLogger(__name__)


def register_bank_movements_crud_routes(router, templates):
    """Register bank movement CRUD routes."""

    @router.post("/bank/matches/{match_id}/confirm", response_class=JSONResponse)
    def portal_bank_match_confirm(match_id: int, issuer: dict = Depends(get_portal_issuer)):
        if int(issuer.get("id") or 0) <= 0:
            raise HTTPException(status_code=401, detail="Sesion invalida")
        ok = match_confirm(match_id, int(issuer["id"]))
        if not ok:
            raise HTTPException(status_code=404, detail="Match no encontrado")
        return JSONResponse({"ok": True, "status": "confirmed"})

    @router.post("/bank/matches/{match_id}/reject", response_class=JSONResponse)
    def portal_bank_match_reject(match_id: int, issuer: dict = Depends(get_portal_issuer)):
        if int(issuer.get("id") or 0) <= 0:
            raise HTTPException(status_code=401, detail="Sesion invalida")
        ok = match_reject(match_id, int(issuer["id"]))
        if not ok:
            raise HTTPException(status_code=404, detail="Match no encontrado")
        return JSONResponse({"ok": True, "status": "rejected"})

    @router.patch("/bank/movements/{movement_id}", response_class=JSONResponse)
    async def portal_bank_movement_update(
        movement_id: int,
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
    ):
        """Actualiza descripcion y/o categoria de un movimiento."""
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesion invalida")
        try:
            body = await request.json() if request.headers.get("content-type", "").strip().startswith("application/json") else {}
        except Exception:
            body = {}
        descripcion = body.get("descripcion")
        categoria = body.get("categoria")
        if descripcion is None and categoria is None:
            return JSONResponse({"ok": True, "updated": False})
        conn = db()
        try:
            row = conn.execute(
                "SELECT id, descripcion, categoria FROM bank_movements WHERE id = ? AND issuer_id = ?",
                (movement_id, issuer_id),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Movimiento no encontrado")
            old_row = _db_row_to_dict(row)
            updates = []
            params: list = []
            if descripcion is not None:
                updates.append("descripcion = ?")
                params.append(str(descripcion).strip() if descripcion else "")
            if categoria is not None:
                updates.append("categoria = ?")
                params.append(str(categoria).strip() if categoria else "")
            if not updates:
                return JSONResponse({"ok": True, "updated": False})
            params.extend([movement_id, issuer_id])
            conn.execute(
                "UPDATE bank_movements SET " + ", ".join(updates) + " WHERE id = ? AND issuer_id = ?",
                params,
            )
            # Audit trail
            user_id = getattr(request.state, "user_id", None)
            if table_exists(conn, "bank_movement_edits"):
                if descripcion is not None and str(descripcion).strip() != (old_row.get("descripcion") or ""):
                    conn.execute(
                        "INSERT INTO bank_movement_edits (issuer_id, movement_id, field_name, old_value, new_value, edited_by) VALUES (?, ?, 'descripcion', ?, ?, ?)",
                        (issuer_id, movement_id, old_row.get("descripcion") or "", str(descripcion).strip(), user_id),
                    )
                if categoria is not None and str(categoria).strip() != (old_row.get("categoria") or ""):
                    conn.execute(
                        "INSERT INTO bank_movement_edits (issuer_id, movement_id, field_name, old_value, new_value, edited_by) VALUES (?, ?, 'categoria', ?, ?, ?)",
                        (issuer_id, movement_id, old_row.get("categoria") or "", str(categoria).strip(), user_id),
                    )
            conn.commit()
            return JSONResponse({"ok": True, "updated": True})
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    @router.get("/bank/movements/{movement_id}/edits", response_class=JSONResponse)
    def portal_bank_movement_edits(movement_id: int, issuer: dict = Depends(get_portal_issuer)):
        """Returns edit history for a movement."""
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesion invalida")
        conn = db()
        try:
            if not table_exists(conn, "bank_movement_edits"):
                return JSONResponse({"ok": True, "edits": []})
            rows = conn.execute(
                "SELECT field_name, old_value, new_value, created_at FROM bank_movement_edits WHERE movement_id = ? AND issuer_id = ? ORDER BY created_at DESC LIMIT 50",
                (movement_id, issuer_id),
            ).fetchall()
            edits = [_db_row_to_dict(r) for r in rows]
            return JSONResponse({"ok": True, "edits": edits})
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @router.post("/bank/movements/delete-all", response_class=JSONResponse)
    def portal_bank_movements_delete_all(issuer: dict = Depends(get_portal_issuer)):
        """Borra todos los movimientos bancarios del emisor actual. Requiere confirmacion en el cliente."""
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesion invalida")
        conn = db()
        try:
            cur = conn.execute("DELETE FROM bank_movements WHERE issuer_id = ?", (issuer_id,))
            deleted = cur.rowcount
            conn.commit()
            return JSONResponse({"ok": True, "deleted": deleted})
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
