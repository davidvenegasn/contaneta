"""Bank PDF upload and convert route — saves PDF, converts to XLSX, persists movements."""
import hashlib
import json
import logging
import os
import secrets
from datetime import datetime
from typing import Optional

from fastapi import Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from config import BASE_DIR
from database import db, has_column
from routers.deps import get_portal_issuer
from routers.portal._helpers import render_portal
from routers.portal.bank._bank_helpers import (
    MAX_BANK_PDF_SIZE,
    ensure_bank_exports_table,
    ensure_bank_movements_table,
    ensure_bank_statements_table,
)
from services.action_log import log_action
from services.auth import rate_limit as rate_limit_service
from services.bank.bank_accounts import list_active_accounts_raw as bank_list_accounts_raw
from services.bank.bank_own_accounts import detect_own_account_transfer, reclassify_own_transfers_by_rfc
from services.bank.bank_parse_preview import parse_bank_pdf_to_movements_preview
from services.bank.bank_preview_pipeline import parse_bank_statement_preview
from services.bank.bank_statement_ingest import extract_statement_metadata
from services.pdf_to_excel import convert_pdf_to_xlsx, ensure_parent_dir, get_storage_root, safe_join
from services.portal_errors import portal_error_type

logger = logging.getLogger(__name__)


def register_bank_pdf_upload_routes(router, templates):
    """Register PDF upload/convert routes."""

    def _render_portal(request, **kwargs):
        return render_portal(templates, request, **kwargs)

    @router.post("/bank/pdf-to-excel/upload")
    async def portal_bank_pdf_to_excel_upload(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        file: UploadFile = File(...),
        preview: Optional[str] = Form(None),
    ):
        if rate_limit_service.is_rate_limited(request, "bank_pdf_upload", max_attempts=10, window_seconds=60):
            raise HTTPException(status_code=429, detail="Demasiadas solicitudes. Intenta en un momento.")
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesion invalida")

        # Validaciones basicas
        filename = (file.filename or "").strip()
        name_l = filename.lower()
        if not name_l.endswith(".pdf"):
            raise HTTPException(status_code=400, detail="El archivo debe ser .pdf")
        content_type = (file.content_type or "").lower().strip()
        if content_type and content_type not in ("application/pdf", "application/x-pdf"):
            raise HTTPException(status_code=400, detail="El archivo debe ser un PDF valido (MIME application/pdf)")

        # Leer PDF en memoria
        sha = hashlib.sha256()
        size = 0
        chunks: list[bytes] = []
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BANK_PDF_SIZE:
                raise HTTPException(status_code=400, detail="El PDF excede el maximo de 15MB.")
            sha.update(chunk)
            chunks.append(chunk)
        if size <= 0:
            raise HTTPException(status_code=400, detail="El PDF esta vacio.")
        pdf_bytes_head = chunks[0] if chunks else b""
        if not pdf_bytes_head.startswith(b"%PDF"):
            raise HTTPException(status_code=400, detail="El archivo no es un PDF valido.")

        # Vista previa Banorte: solo parsear y devolver HTML (no DB, no XLSX)
        if preview and str(preview).strip().lower() in ("1", "true", "yes"):
            import tempfile
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    for ch in chunks:
                        tmp.write(ch)
                    tmp_path = tmp.name
                result = parse_bank_pdf_to_movements_preview(tmp_path)
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass
            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_bank_pdf_to_excel.html",
                active_page="bank_pdf_to_excel",
                title="Convertir Edo. de Cuenta",
                extra={
                    "preview_movements": result.get("movements") or [],
                    "preview_summary": result.get("summary") or {},
                },
            )

        storage_root = get_storage_root(BASE_DIR)
        uploads_rel_dir = os.path.join("uploads", str(issuer_id), "bank")
        exports_rel_dir = os.path.join("exports", str(issuer_id), "bank_statements")

        pdf_sha256 = sha.hexdigest()
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        pdf_name = f"{stamp}_{pdf_sha256[:12]}.pdf"
        pdf_rel_path = os.path.join(uploads_rel_dir, pdf_name)
        pdf_abs_path = safe_join(storage_root, pdf_rel_path)
        ensure_parent_dir(pdf_abs_path)
        with open(pdf_abs_path, "wb") as f:
            for ch in chunks:
                f.write(ch)

        pdf_bytes = b"".join(chunks)
        # Get or create bank_statement (dedupe por mismo PDF). Validar RFC antes de guardar.
        conn = db()
        upload_metadata = {}
        result_preview = parse_bank_statement_preview(pdf_bytes, file_name=filename or "documento.pdf", file_index=0)
        if not result_preview.get("file_error"):
            upload_metadata = extract_statement_metadata(result_preview)
            detected_rfc = (upload_metadata.get("detected_holder_rfc") or "").strip().upper().replace(" ", "")
            expected_rfc = (issuer.get("rfc") or "").strip().upper().replace(" ", "")
            if expected_rfc and detected_rfc and expected_rfc != detected_rfc:
                raise HTTPException(
                    status_code=400,
                    detail="El RFC del estado de cuenta no coincide con el RFC de tu cuenta. No se puede procesar este PDF.",
                )
        try:
            ensure_bank_statements_table(conn)
            row = conn.execute(
                "SELECT id FROM bank_statements WHERE issuer_id = ? AND source_pdf_sha256 = ? LIMIT 1",
                (issuer_id, pdf_sha256),
            ).fetchone()
            if row:
                statement_id = int(row["id"])
            else:
                conn.execute(
                    """
                    INSERT INTO bank_statements (issuer_id, source_pdf_path, source_pdf_sha256, created_at)
                    VALUES (?, ?, ?, datetime('now'))
                    """,
                    (issuer_id, pdf_rel_path, pdf_sha256),
                )
                statement_id = conn.execute("SELECT last_insert_rowid() AS rid").fetchone()["rid"]
                conn.commit()
            period_month = (upload_metadata.get("period_month") or "")[:7]
            if period_month and has_column(conn, "bank_statements", "period_month"):
                conn.execute(
                    "UPDATE bank_statements SET period_month = ?, bank_name = ?, account_last4 = ? WHERE id = ? AND issuer_id = ?",
                    (period_month, upload_metadata.get("bank_name"), upload_metadata.get("account_last4"), statement_id, issuer_id),
                )
                conn.commit()
        finally:
            conn.close()

        file_id = secrets.token_urlsafe(16)
        xlsx_name = f"{stamp}_{file_id[:10]}.xlsx"
        xlsx_rel_path = os.path.join(exports_rel_dir, xlsx_name)
        xlsx_abs_path = safe_join(storage_root, xlsx_rel_path)

        try:
            meta = convert_pdf_to_xlsx(
                pdf_abs_path,
                xlsx_abs_path,
                issuer_id=issuer_id,
                statement_id=statement_id,
            )
        except Exception as e:
            logger.exception("bank pdf-to-excel: error convirtiendo issuer=%s pdf=%s", issuer_id, pdf_rel_path)
            portal_error_type("parse_fail", log_context={"issuer_id": issuer_id, "pdf": pdf_rel_path})

        meta_for_storage = {k: v for k, v in (meta or {}).items() if k != "transactions"}
        meta_json_str = json.dumps(meta_for_storage, ensure_ascii=False)[:4000]

        conn = db()
        try:
            ensure_bank_exports_table(conn)
            ensure_bank_movements_table(conn)
            conn.execute(
                """
                INSERT INTO bank_pdf_exports (issuer_id, file_id, pdf_path, xlsx_path, meta_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (issuer_id, file_id, pdf_rel_path, xlsx_rel_path, meta_json_str),
            )
            default_period = (upload_metadata.get("period_month") or (meta or {}).get("period_start") or "")[:7]
            mov_has_period = has_column(conn, "bank_movements", "period_month")
            mov_has_hash = has_column(conn, "bank_movements", "movement_hash")
            user_accounts = bank_list_accounts_raw(int(issuer_id)) if int(issuer_id) > 0 else []
            statement_owner_name = (upload_metadata.get("detected_holder_name") or "").strip() or None
            statement_owner_rfc = (upload_metadata.get("detected_holder_rfc") or "").strip() or None
            # Post-process: apply category rules (own-account transfers, card payments)
            # then update movements already inserted by upsert_bank_movements()
            for t in (meta or {}).get("transactions") or []:
                fecha = (t.get("fecha") or "")[:32]
                descripcion = (t.get("descripcion") or "")[:2000]
                deposito = t.get("deposito")
                retiro = t.get("retiro")
                tipo = (t.get("tipo") or "").strip().upper()
                if tipo not in ("INGRESO", "GASTO"):
                    continue
                try:
                    desc_norm = (descripcion or "").strip().upper()
                    mov_hint = {
                        "raw_text_original": descripcion,
                        "raw_text_normalized": desc_norm,
                        "referencia": "",
                        "contraparte_nombre": (t.get("contraparte_hint") or "").strip(),
                        "rfc_detectado": (t.get("rfc_encontrado") or "").strip(),
                        "tipo_movimiento": tipo,
                        "monto_deposito": float(deposito or 0),
                        "monto_retiro": float(retiro or 0),
                        "categoria_sugerida": (t.get("categoria") or "").strip(),
                        "warnings": [],
                    }
                    issuer_rfc_auto = (issuer.get("rfc") or "").strip().upper()
                    detect_own_account_transfer(mov_hint, user_accounts, statement_owner_name, statement_owner_rfc, issuer_rfc=issuer_rfc_auto)
                    new_cat = None
                    if mov_hint.get("es_transferencia_propia_probable"):
                        new_cat = "CUENTA_PROPIA"
                    else:
                        metodo = (t.get("metodo_hint") or "").upper()
                        if (
                            ("PAGO CONCENTRACION" in desc_norm or "PAGO TARJETA" in desc_norm or "TARJETA DE CRED" in desc_norm)
                            or ("TARJETA" in metodo and "PAGO" in desc_norm)
                        ):
                            new_cat = "FINANCIERO_PAGO_TARJETA"
                    if new_cat and mov_has_hash:
                        from services.bank.bank_statement_parser import _movement_hash
                        h = _movement_hash(issuer_id, t)
                        conn.execute(
                            "UPDATE bank_movements SET categoria = ? WHERE issuer_id = ? AND movement_hash = ?",
                            (new_cat, issuer_id, h),
                        )
                except Exception:
                    pass
            conn.commit()
            # Retroactive: reclassify any movements matching issuer RFC
            _auto_rfc = (issuer.get("rfc") or "").strip().upper()
            if _auto_rfc:
                reclassify_own_transfers_by_rfc(conn, int(issuer_id), _auto_rfc)
        finally:
            conn.close()

        log_action(request, "bank_pdf_to_excel", issuer_id=issuer_id, entity_id=file_id[:32])
        # Campos resumidos para UI (ademas de meta completo)
        try:
            processed_count = int((meta or {}).get("processed_count") or 0)
        except Exception:
            processed_count = 0
        try:
            total_ingresos = float((meta or {}).get("total_ingresos") or 0)
        except Exception:
            total_ingresos = 0.0
        try:
            total_gastos = float((meta or {}).get("total_gastos") or 0)
        except Exception:
            total_gastos = 0.0
        try:
            sin_factura_count = int((meta or {}).get("sin_factura_count") or 0)
        except Exception:
            sin_factura_count = 0
        try:
            movements_count = int((meta or {}).get("movements_count") or 0)
        except Exception:
            movements_count = 0
        try:
            ingresos_total = float((meta or {}).get("ingresos_total") or 0)
        except Exception:
            ingresos_total = 0.0
        try:
            gastos_total = float((meta or {}).get("gastos_total") or 0)
        except Exception:
            gastos_total = 0.0
        try:
            sin_parse_count = int((meta or {}).get("sin_parse_count") or 0)
        except Exception:
            sin_parse_count = 0
        quality = (meta or {}).get("quality") if isinstance((meta or {}).get("quality"), dict) else None
        try:
            low_confidence_count = int((meta or {}).get("low_confidence_count") or 0)
        except Exception:
            low_confidence_count = 0
        return JSONResponse(
            {
                "ok": True,
                "file_id": file_id,
                "statement_id": statement_id,
                "meta": meta,
                "processed_count": processed_count,
                "total_ingresos": total_ingresos,
                "total_gastos": total_gastos,
                "sin_factura_count": sin_factura_count,
                "movements_count": movements_count,
                "ingresos_total": ingresos_total,
                "gastos_total": gastos_total,
                "sin_parse_count": sin_parse_count,
                "low_confidence_count": low_confidence_count,
                "quality": quality,
                "download_url": f"/portal/bank/pdf-to-excel/download/{file_id}",
            }
        )
