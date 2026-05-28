"""Auth onboarding routes: confirmar-perfil, onboarding wizard, terms, privacy."""
from fastapi import Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from database import db, db_rows, has_column
from services.auth import csrf as csrf_service
from services.auth import session, users


def register_onboarding_routes(router, templates):
    """Register confirmar-perfil, onboarding, terms, and privacy routes."""
    cookie_name = session.get_session_cookie_name()

    @router.get("/terms", response_class=HTMLResponse)
    def terms_page(request: Request):
        return templates.TemplateResponse(request, "terms.html", {})

    @router.get("/privacy", response_class=HTMLResponse)
    def privacy_page(request: Request):
        return templates.TemplateResponse(request, "privacy.html", {})

    @router.get("/confirmar-perfil", response_class=HTMLResponse)
    def confirmar_perfil_page(request: Request):
        cookie_val = request.cookies.get(cookie_name)
        session_data = session.verify_session(cookie_val)
        if not session_data or session_data[0] == 0:
            return RedirectResponse(url="/login", status_code=302)
        user_id = session_data[0]
        user = users.get_user_by_id(user_id)
        if not user:
            return RedirectResponse(url="/login", status_code=302)
        memberships = users.get_memberships_for_user(user_id)
        if memberships:
            return RedirectResponse(url="/portal/home", status_code=302)
        return templates.TemplateResponse(
            request,
            "confirmar_perfil.html",
            {"user": user, "error": request.query_params.get("error"), "csrf_token": csrf_service.generate_csrf_token()},
        )

    @router.post("/confirmar-perfil", response_class=RedirectResponse)
    def confirmar_perfil_submit(request: Request, name: str | None = Form(None), csrf_token: str | None = Form(None)):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            return RedirectResponse(url="/confirmar-perfil?error=invalid", status_code=302)
        cookie_val = request.cookies.get(cookie_name)
        session_data = session.verify_session(cookie_val)
        if not session_data or session_data[0] == 0:
            return RedirectResponse(url="/login", status_code=302)
        user_id = session_data[0]
        users.update_user_name(user_id, name)
        user = users.get_user_by_id(user_id)
        razon_social = (name or "").strip() or (user.get("email") or "").strip() or "Mi empresa"
        conn = db()
        try:
            cur = conn.execute(
                """INSERT INTO issuers (rfc, razon_social, regimen_fiscal, active)
                   VALUES (?, ?, ?, 1)""",
                ("PENDIENTE", razon_social, None),
            )
            issuer_id = cur.lastrowid
            if has_column(conn, "issuers", "trial_expires_at"):
                conn.execute(
                    "UPDATE issuers SET trial_expires_at = datetime('now', '+14 days') WHERE id = ?",
                    (issuer_id,),
                )
            conn.commit()
        finally:
            conn.close()
        users.add_membership(user_id, issuer_id, "owner")
        resp = RedirectResponse(url="/portal/config/sat", status_code=302)
        resp.set_cookie(
            cookie_name,
            session.sign_session(user_id, issuer_id),
            **session.session_cookie_params(request),
        )
        return resp

    @router.get("/onboarding", response_class=HTMLResponse)
    def onboarding_page(request: Request):
        """Multi-step onboarding wizard: fiscal data -> SAT setup -> first invoice."""
        cookie_val = request.cookies.get(cookie_name)
        session_data = session.verify_session(cookie_val)
        if not session_data or session_data[0] == 0:
            return RedirectResponse(url="/login", status_code=302)
        user_id, issuer_id = session_data[0], session_data[1]
        error = request.query_params.get("error")

        # Determine which step the user is on based on their data
        issuer = None
        step = 1  # default: fiscal data
        has_customers = False
        has_products = False
        if issuer_id and issuer_id > 0:
            rows = db_rows("SELECT * FROM issuers WHERE id = ?", (issuer_id,))
            issuer = rows[0] if rows else None
        rfc_ok = bool(issuer and issuer.get("rfc") and issuer["rfc"] != "PENDIENTE")
        if rfc_ok:
            # Check if FIEL is configured
            has_fiel = bool(db_rows(
                "SELECT 1 FROM sat_credentials WHERE issuer_id = ? LIMIT 1",
                (issuer_id,),
            ))
            if has_fiel:
                # Check customers/products for step 3
                cust = db_rows(
                    "SELECT COUNT(*) AS n FROM customer_profiles WHERE issuer_id = ?",
                    (issuer_id,),
                )
                prod = db_rows(
                    "SELECT COUNT(*) AS n FROM products WHERE issuer_id = ?",
                    (issuer_id,),
                )
                has_customers = bool(cust and cust[0]["n"] > 0)
                has_products = bool(prod and prod[0]["n"] > 0)
                step = 3
            else:
                step = 2

        # Allow explicit step override via query param (within valid range)
        forced = request.query_params.get("step")
        if forced and forced.isdigit() and 1 <= int(forced) <= 3:
            step = int(forced)

        return templates.TemplateResponse(
            "onboarding.html",
            {
                "request": request,
                "step": step,
                "issuer": issuer,
                "error": error,
                "csrf_token": csrf_service.generate_csrf_token(),
                "has_customers": has_customers,
                "has_products": has_products,
            },
        )

    @router.post("/onboarding", response_class=RedirectResponse)
    def onboarding_submit(
        request: Request,
        rfc: str = Form(...),
        razon_social: str = Form(...),
        regimen_fiscal: str = Form("616"),
        cp: str | None = Form(None),
        authorize_firm: str | None = Form(None),
        csrf_token: str | None = Form(None),
    ):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            return RedirectResponse(url="/onboarding?error=invalid", status_code=302)
        cookie_val = request.cookies.get(cookie_name)
        session_data = session.verify_session(cookie_val)
        if not session_data or session_data[0] == 0:
            return RedirectResponse(url="/login", status_code=302)
        user_id, issuer_id = session_data[0], session_data[1]
        rfc = (rfc or "").strip().upper()
        razon_social = (razon_social or "").strip()
        if not rfc or not razon_social:
            return RedirectResponse(url="/onboarding?error=required", status_code=302)
        conn = db()
        try:
            if issuer_id and issuer_id > 0:
                conn.execute(
                    """UPDATE issuers SET rfc = ?, razon_social = ?, regimen_fiscal = ?, updated_at = datetime('now')
                       WHERE id = ?""",
                    (rfc, razon_social, (regimen_fiscal or "").strip() or None, issuer_id),
                )
            else:
                cur = conn.execute(
                    """INSERT INTO issuers (rfc, razon_social, regimen_fiscal, active)
                       VALUES (?, ?, ?, 1)""",
                    (rfc, razon_social, (regimen_fiscal or "").strip() or None),
                )
                issuer_id = cur.lastrowid
                if has_column(conn, "issuers", "trial_expires_at"):
                    conn.execute(
                        "UPDATE issuers SET trial_expires_at = datetime('now', '+14 days') WHERE id = ?",
                        (issuer_id,),
                    )
                users.add_membership(user_id, issuer_id, "owner")
            if authorize_firm == "on":
                firm_id = users.get_firm_user_id()
                if firm_id:
                    users.add_membership(firm_id, issuer_id, "accountant")
            conn.commit()
        finally:
            conn.close()
        # Redirect to step 2 (SAT setup) after saving fiscal data
        resp = RedirectResponse(url="/onboarding?step=2", status_code=302)
        resp.set_cookie(
            cookie_name,
            session.sign_session(user_id, issuer_id),
            **session.session_cookie_params(request),
        )
        return resp
