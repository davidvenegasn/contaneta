"""Bank statement ingestion route."""
import hashlib
import logging
import os
from datetime import datetime

from fastapi import Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from config import BASE_DIR
from database import db, table_exists
from routers.deps import get_portal_issuer
from routers.portal._helpers import _db_row_to_dict
from routers.portal.bank._bank_helpers import MAX_BANK_PDF_SIZE
from services.action_log import log_action
from services.auth import rate_limit as rate_limit_service
from services.bank.bank_cfdi_matching import find_cfdi_candidates, save_suggested_matches
from services.bank.bank_preview_pipeline import parse_bank_statement_preview
from services.bank.bank_statement_ingest import ingest_bank_statement
from services.pdf_to_excel import ensure_parent_dir, get_storage_root, safe_join

logger = logging.getLogger(__name__)


def register_bank_ingest_routes(router, templates):
    """Register bank statement ingestion routes."""

    @router.post("/bank/statements/ingest", response_class=JSONResponse)
    async def portal_bank_statements_ingest(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        file: UploadFile = File(...),
        bank_account_id: int = Form(..., description="ID de cuenta bancaria del issuer"),
    ):
        """Ingesta estado de cuenta con validacion RFC/cuenta. Fases 2+3."""
        if rate_limit_service.is_rate_limited(request, "bank_ingest", max_attempts=10, window_seconds=60):
            raise HTTPException(status_code=429, detail="Demasiadas solicitudes. Intenta en un momento.")
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesion invalida")
        fn = (file.filename or "").strip()
        if not fn.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="El archivo debe ser .pdf")
        size = 0
        chunks = []
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BANK_PDF_SIZE:
                raise HTTPException(status_code=400, detail="El PDF excede el maximo de 15MB.")
            chunks.append(chunk)
        if size <= 0:
            raise HTTPException(status_code=400, detail="El PDF esta vacio.")
        pdf_bytes = b"".join(chunks)
        if not pdf_bytes.startswith(b"%PDF"):
            raise HTTPException(status_code=400, detail="El archivo no es un PDF valido.")
        sha = hashlib.sha256(pdf_bytes).hexdigest()
        result = parse_bank_statement_preview(pdf_bytes, file_name=fn, file_index=0)
        if result.get("file_error"):
            return JSONResponse(
                {"ok": False, "rejection_reason": result["file_error"], "status": "parse_error"},
                status_code=400,
            )
        storage_root = get_storage_root(BASE_DIR)
        uploads_rel = os.path.join("uploads", str(issuer_id), "bank")
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        pdf_name = f"{stamp}_{sha[:12]}.pdf"
        pdf_rel_path = os.path.join(uploads_rel, pdf_name)
        pdf_abs_path = safe_join(storage_root, pdf_rel_path)
        ensure_parent_dir(pdf_abs_path)
        with open(pdf_abs_path, "wb") as f:
            f.write(pdf_bytes)
        expected_rfc = (issuer.get("rfc") or "").strip()
        ingest_result = ingest_bank_statement(
            issuer_id=issuer_id,
            bank_account_id=bank_account_id,
            pdf_path=pdf_rel_path,
            pdf_sha256=sha,
            source_file_name=fn,
            preview_result=result,
            expected_issuer_rfc=expected_rfc,
        )
        if not ingest_result.get("ok"):
            return JSONResponse(
                {
                    "ok": False,
                    "rejection_reason": ingest_result.get("rejection_reason", "Error desconocido"),
                    "status": ingest_result.get("status", "error"),
                },
                status_code=400,
            )
        statement_id = ingest_result.get("statement_id")
        movements_count = ingest_result.get("movements_count", 0)
        if statement_id and movements_count > 0 and table_exists(db(), "bank_invoice_matches"):
            try:
                conn = db()
                rows = conn.execute(
                    "SELECT id, deposito, retiro, amount, fecha, descripcion, rfc_encontrado, counterparty_rfc_detected, requires_cfdi FROM bank_movements WHERE issuer_id = ? AND bank_statement_id = ?",
                    (issuer_id, statement_id),
                ).fetchall()
                conn.close()
                for r in rows:
                    r = _db_row_to_dict(r)
                    if int(r.get("requires_cfdi") or 0):
                        mov = r
                        candidates = find_cfdi_candidates(issuer_id, mov, direction="received", limit=5)
                        if candidates:
                            save_suggested_matches(issuer_id, int(r["id"]), candidates, "payment")
            except Exception as e:
                logger.exception("bank ingest: matching post-insert failed: %s", e)
        log_action(request, "bank_statement_ingest", issuer_id=issuer_id, entity_id=statement_id)
        return JSONResponse({
            "ok": True,
            "statement_id": statement_id,
            "movements_count": movements_count,
            "inserted_count": ingest_result.get("inserted_count", movements_count),
            "duplicate_movements_count": ingest_result.get("duplicate_movements_count", 0),
            "duplicate": ingest_result.get("duplicate", False),
        })
