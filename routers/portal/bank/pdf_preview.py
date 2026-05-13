"""Bank PDF preview routes — parse PDFs and return movements without DB persistence."""
import logging
import os
from datetime import datetime, timezone

from fastapi import Depends, File, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException

from routers.deps import get_portal_issuer
from routers.portal.bank._bank_helpers import (
    MAX_BANK_PDF_FILES,
    MAX_BANK_PDF_SIZE,
    MAX_BANK_PDF_TOTAL_SIZE,
    ensure_bank_movements_table,
)
from services.auth import rate_limit as rate_limit_service
from services.bank.bank_accounts import list_active_accounts_raw as bank_list_accounts_raw
from services.bank.bank_own_accounts import detect_own_account_transfer
from services.bank.bank_parse_preview import parse_bank_pdf_to_movements_preview
from services.bank.bank_preview_models import compute_dedupe_fingerprint
from services.bank.bank_preview_pipeline import parse_bank_statement_preview

logger = logging.getLogger(__name__)


def register_bank_pdf_preview_routes(router, templates):
    """Register PDF preview routes (preview-json, preview-multi)."""

    @router.get("/bank/pdf-to-excel", response_class=RedirectResponse)
    def portal_bank_pdf_to_excel_redirect():
        """Redirigir al nombre canonico de la pagina."""
        return RedirectResponse(url="/portal/convertir-edo-cuenta", status_code=302)

    @router.post("/bank/pdf-to-excel/preview-json", response_class=JSONResponse)
    async def portal_bank_pdf_preview_json(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        file: UploadFile = File(...),
    ):
        """Parsea PDF Banorte y devuelve movimientos en JSON. Sin DB, sin guardar. Para mostrar listado en la misma pagina."""
        if rate_limit_service.is_rate_limited(request, "bank_pdf_preview", max_attempts=10, window_seconds=60):
            raise HTTPException(status_code=429, detail="Demasiadas solicitudes. Intenta en un momento.")
        if int(issuer.get("id") or 0) <= 0:
            raise HTTPException(status_code=401, detail="Sesion invalida")
        filename = (file.filename or "").strip().lower()
        if not filename.endswith(".pdf"):
            raise HTTPException(status_code=400, detail="El archivo debe ser .pdf")
        content_type = (file.content_type or "").lower().strip()
        if content_type and content_type not in ("application/pdf", "application/x-pdf"):
            raise HTTPException(status_code=400, detail="Tipo de archivo invalido (solo PDF).")
        size = 0
        chunks: list[bytes] = []
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
        # Magic bytes minimo: evita 500 en el parser legacy por archivo no-PDF
        if chunks and not chunks[0].startswith(b"%PDF-"):
            raise HTTPException(status_code=400, detail="El archivo no parece ser un PDF valido.")
        import tempfile
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                for ch in chunks:
                    tmp.write(ch)
                tmp_path = tmp.name
            try:
                result = parse_bank_pdf_to_movements_preview(tmp_path, preset="conservative")
            except Exception:
                raise HTTPException(status_code=400, detail="No pudimos leer el PDF. Verifica que sea un estado de cuenta valido.")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
        movements = result.get("movements") or []
        summary = result.get("summary") or {}
        if summary.get("error"):
            return JSONResponse(
                {"ok": False, "detail": summary.get("error"), "movements": [], "summary": summary},
                status_code=400,
            )
        if not movements:
            logger.warning(
                "preview-json: 0 movements from PDF '%s' (rows=%s, sections=%s, txs=%s, bank=%s)",
                file.filename,
                summary.get("raw_rows_count", "?"),
                summary.get("sections_detected", "?"),
                summary.get("txs_grouped_count", "?"),
                summary.get("bank_name", "?"),
            )
        return JSONResponse({"ok": True, "movements": movements, "summary": summary})

    @router.post("/bank/pdf-to-excel/preview-multi", response_class=JSONResponse)
    async def portal_bank_pdf_preview_multi(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        files: list[UploadFile] = File(..., description="PDFs de estados de cuenta"),
    ):
        """Multi-PDF preview: procesa varios PDFs, consolidado en memoria. Sin DB."""
        if rate_limit_service.is_rate_limited(request, "bank_pdf_preview", max_attempts=10, window_seconds=60):
            raise HTTPException(status_code=429, detail="Demasiadas solicitudes. Intenta en un momento.")
        if int(issuer.get("id") or 0) <= 0:
            raise HTTPException(status_code=401, detail="Sesion invalida")
        if not files or len(files) > MAX_BANK_PDF_FILES:
            raise HTTPException(
                status_code=400,
                detail=f"Envia entre 1 y {MAX_BANK_PDF_FILES} archivos PDF.",
            )
        all_movements: list[dict] = []
        files_summary: list[dict] = []
        file_errors: list[dict] = []
        file_warnings: list[dict] = []
        total_size = 0
        for idx, uf in enumerate(files):
            fn = (uf.filename or "").strip()
            if not fn.lower().endswith(".pdf"):
                file_errors.append({"file_name": fn or f"archivo_{idx + 1}", "error": "El archivo debe ser .pdf"})
                continue
            chunks = []
            size = 0
            while True:
                chunk = await uf.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BANK_PDF_SIZE:
                    file_errors.append({"file_name": fn, "error": "El PDF excede el maximo de 15MB."})
                    break
                chunks.append(chunk)
            if size > MAX_BANK_PDF_SIZE:
                continue
            total_size += size
            if total_size > MAX_BANK_PDF_TOTAL_SIZE:
                file_errors.append({"file_name": fn, "error": "Se supero el tamano total permitido (50MB)."})
                continue
            if size <= 0:
                file_errors.append({"file_name": fn, "error": "El PDF esta vacio."})
                continue
            pdf_bytes = b"".join(chunks)
            if not pdf_bytes.startswith(b"%PDF"):
                file_errors.append({"file_name": fn, "error": "El archivo no es un PDF valido."})
                continue
            result = parse_bank_statement_preview(pdf_bytes, file_name=fn, file_index=idx)
            movs = result.get("movements") or []
            fs = result.get("file_summary") or {}
            err = result.get("file_error")
            warns = result.get("file_warnings") or []
            if err:
                file_errors.append({"file_name": fn, "error": err})
            if warns:
                file_warnings.append({"file_name": fn, "warnings": warns})
            files_summary.append(fs)
            base_idx = len(all_movements)
            for i, m in enumerate(movs):
                m["_global_idx"] = base_idx + i + 1
            all_movements.extend(movs)
        # Marcar duplicados por fingerprint (misma fecha+monto+concepto+archivo)
        fp_counts: dict[str, int] = {}
        for m in all_movements:
            fp = m.get("dedupe_fingerprint") or compute_dedupe_fingerprint(m)
            m["dedupe_fingerprint"] = fp
            fp_counts[fp] = fp_counts.get(fp, 0) + 1
        for m in all_movements:
            if fp_counts.get(m["dedupe_fingerprint"], 0) > 1:
                m["posible_duplicado"] = True
                w = m.get("warnings") or []
                if "Posible duplicado en esta carga" not in w:
                    w.append("Posible duplicado en esta carga")
                m["warnings"] = w
        issuer_id = int(issuer.get("id") or 0)
        user_accounts = bank_list_accounts_raw(issuer_id) if issuer_id > 0 else []
        statement_owner_name = None
        statement_owner_rfc = None
        if files_summary:
            fs = next((f for f in files_summary if f.get("account_holder_name")), None)
            if fs:
                statement_owner_name = fs.get("account_holder_name")
                statement_owner_rfc = fs.get("account_holder_rfc")
        issuer_rfc = (issuer.get("rfc") or "").strip().upper()
        for m in all_movements:
            detect_own_account_transfer(m, user_accounts, statement_owner_name, statement_owner_rfc, issuer_rfc=issuer_rfc)
        total_ing = sum(m.get("monto_deposito") or 0 for m in all_movements)
        total_gas = sum(m.get("monto_retiro") or 0 for m in all_movements)
        total_ing_impactan = sum(
            (m.get("monto_deposito") or 0) for m in all_movements
            if m.get("impacta_contabilidad", True) and (m.get("tipo_movimiento") or "").upper() == "INGRESO"
        )
        total_gas_impactan = sum(
            (m.get("monto_retiro") or 0) for m in all_movements
            if m.get("impacta_contabilidad", True) and (m.get("tipo_movimiento") or "").upper() == "GASTO"
        )
        count_in = sum(1 for m in all_movements if (m.get("tipo_movimiento") or "").upper() == "INGRESO")
        count_out = sum(1 for m in all_movements if (m.get("tipo_movimiento") or "").upper() == "GASTO")
        count_info = sum(1 for m in all_movements if (m.get("tipo_movimiento") or "").upper() == "INFO")
        count_fin = sum(1 for m in all_movements if m.get("es_movimiento_financiero"))
        low_conf = sum(1 for m in all_movements if int(m.get("confianza_clasificacion") or 0) < 60)
        count_revisar = sum(1 for m in all_movements if m.get("requiere_revision"))
        count_duplicados = sum(1 for m in all_movements if m.get("posible_duplicado"))
        global_summary = {
            "files_processed": len(files_summary),
            "files_with_errors": len(file_errors),
            "total_movements": len(all_movements),
            "total_ingresos": round(total_ing, 2),
            "total_gastos": round(total_gas, 2),
            "total_ingresos_que_impactan": round(total_ing_impactan, 2),
            "total_gastos_que_impactan": round(total_gas_impactan, 2),
            "count_ingreso": count_in,
            "count_gasto": count_out,
            "count_info": count_info,
            "count_financiero": count_fin,
            "count_low_confidence": low_conf,
            "count_requiere_revision": count_revisar,
            "count_duplicados": count_duplicados,
        }
        # Auto-save movements to DB (no manual step, no bank account required)
        auto_save_result = {"saved": False}
        if all_movements and issuer_id > 0:
            try:
                from database import db as _db
                from services.bank.bank_statement_parser import upsert_bank_movements
                _conn = _db()
                try:
                    ensure_bank_movements_table(_conn)
                    _conn.commit()
                finally:
                    _conn.close()
                # Map preview fields -> upsert_bank_movements format
                mapped = []
                for m in all_movements:
                    tipo_raw = (m.get("tipo_movimiento") or "INFO").upper()
                    if tipo_raw not in ("INGRESO", "GASTO"):
                        continue
                    mapped.append({
                        "tipo": tipo_raw,
                        "fecha": m.get("fecha") or "",
                        "descripcion": m.get("concepto_resumen") or m.get("raw_text_original") or "",
                        "descripcion_full": m.get("raw_text_original") or m.get("concepto_resumen") or "",
                        "descripcion_norm": m.get("raw_text_normalized") or m.get("concepto_resumen") or "",
                        "deposito": m.get("monto_deposito") or 0,
                        "retiro": m.get("monto_retiro") or 0,
                        "saldo": m.get("saldo"),
                        "categoria": m.get("categoria_sugerida") or "",
                        "metodo_hint": m.get("canal") or "",
                        "contraparte_hint": m.get("contraparte_nombre") or "",
                        "referencia": m.get("referencia") or m.get("cve_rastreo") or "",
                        "rfc_encontrado": m.get("rfc_detectado") or "",
                        "confidence_score": m.get("confianza_clasificacion") or 0,
                        "source_page_first": m.get("page_number"),
                    })
                if mapped:
                    count = upsert_bank_movements(issuer_id, statement_id=0, transactions=mapped)
                    # Derive period from first movement
                    first_fecha = (mapped[0].get("fecha") or "")[:7]
                    auto_save_result = {
                        "saved": True,
                        "inserted_count": count,
                        "duplicate_movements_count": 0,
                        "period_month": first_fecha or None,
                    }
                    logger.info("Auto-saved %d movements for issuer %s", count, issuer_id)
            except Exception:
                logger.exception("Auto-save bank movements failed for issuer %s", issuer_id)
        return JSONResponse({
            "ok": True,
            "movements": all_movements,
            "global_summary": global_summary,
            "files_summary": files_summary,
            "file_errors": file_errors,
            "file_warnings": file_warnings,
            "auto_save": auto_save_result,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        })
