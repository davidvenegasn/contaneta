"""Bank account CRUD routes."""
from typing import Optional

from fastapi import Body, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException

from routers.deps import get_portal_issuer
from routers.portal._helpers import render_portal
from services.bank.bank_accounts import create_account as bank_create_account
from services.bank.bank_accounts import delete_account as bank_delete_account
from services.bank.bank_accounts import list_active_accounts as bank_list_accounts
from services.bank.bank_accounts import list_all_accounts as bank_list_all_accounts
from services.bank.bank_accounts import update_account as bank_update_account


def register_bank_accounts_routes(router, templates):
    """Register bank account CRUD routes."""

    def _render_portal(request, **kwargs):
        return render_portal(templates, request, **kwargs)

    @router.get("/bank/accounts", response_class=JSONResponse)
    def portal_bank_accounts_list(issuer: dict = Depends(get_portal_issuer)):
        """Lista cuentas bancarias del usuario (para detectar cuentas propias)."""
        if int(issuer.get("id") or 0) <= 0:
            raise HTTPException(status_code=401, detail="Sesion invalida")
        accounts = bank_list_accounts(int(issuer["id"]))
        return JSONResponse({"ok": True, "accounts": accounts})

    @router.get("/bank/accounts/manage", response_class=HTMLResponse)
    def portal_bank_accounts_manage(request: Request, issuer: dict = Depends(get_portal_issuer)):
        """Pantalla simple: Mis cuentas bancarias (config para detectar traspasos propios)."""
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesion invalida")
        accounts = bank_list_all_accounts(issuer_id)
        return _render_portal(
            request,
            issuer=issuer,
            template_name="portal_bank_accounts.html",
            active_page="bank_accounts",
            title="Mis cuentas bancarias",
            extra={"accounts": accounts or []},
        )

    @router.post("/bank/accounts", response_class=JSONResponse)
    def portal_bank_accounts_create(
        issuer: dict = Depends(get_portal_issuer),
        alias: str = Body(..., embed=True),
        bank_name: str = Body(..., embed=True),
        clabe: Optional[str] = Body(None, embed=True),
        account_last4: Optional[str] = Body(None, embed=True),
        holder_name: Optional[str] = Body(None, embed=True),
        rfc_titular: Optional[str] = Body(None, embed=True),
        is_active: bool = Body(True, embed=True),
    ):
        if int(issuer.get("id") or 0) <= 0:
            raise HTTPException(status_code=401, detail="Sesion invalida")
        created = bank_create_account(
            int(issuer["id"]), alias=alias, bank_name=bank_name,
            clabe=clabe, account_last4=account_last4, holder_name=holder_name,
            rfc_titular=rfc_titular, is_active=is_active,
        )
        if created.get("error"):
            raise HTTPException(status_code=500, detail=created["error"])
        return JSONResponse({"ok": True, "account": created})

    @router.put("/bank/accounts/{account_id}", response_class=JSONResponse)
    def portal_bank_accounts_update(
        account_id: int,
        issuer: dict = Depends(get_portal_issuer),
        payload: dict = Body(...),
    ):
        if int(issuer.get("id") or 0) <= 0:
            raise HTTPException(status_code=401, detail="Sesion invalida")
        allowed = {"alias", "bank_name", "clabe", "account_last4", "holder_name", "rfc_titular", "is_active"}
        kwargs = {k: v for k, v in payload.items() if k in allowed}
        if "account_last4" in kwargs and kwargs["account_last4"]:
            kwargs["account_last4"] = str(kwargs["account_last4"]).strip()[:4]
        updated = bank_update_account(account_id, int(issuer["id"]), **kwargs)
        if not updated:
            raise HTTPException(status_code=404, detail="Cuenta no encontrada")
        return JSONResponse({"ok": True, "account": updated})

    @router.delete("/bank/accounts/{account_id}", response_class=JSONResponse)
    def portal_bank_accounts_delete(account_id: int, issuer: dict = Depends(get_portal_issuer)):
        if int(issuer.get("id") or 0) <= 0:
            raise HTTPException(status_code=401, detail="Sesion invalida")
        deleted = bank_delete_account(account_id, int(issuer["id"]))
        if not deleted:
            raise HTTPException(status_code=404, detail="Cuenta no encontrada")
        return JSONResponse({"ok": True})
