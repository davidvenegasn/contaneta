"""Invoice PDF extraction route."""
import logging
import os
import re
import time
from datetime import datetime

from fastapi import Depends, File, HTTPException, Query, Request, UploadFile

from routers.api._helpers import _api_rate_check
from routers.api.invoices._pdf_parse_helpers import _parse_invoice_text
from routers.deps import get_portal_issuer
from services.auth import csrf as csrf_service
from services.http import ok

logger = logging.getLogger(__name__)


def register_invoices_pdf_extract_routes(router):
    """Register invoice PDF extraction route."""

    @router.post("/invoices/extract-pdf")
    def api_invoice_extract_pdf(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        file: UploadFile = File(...),
        auto_save: bool = Query(False, alias="auto_save"),
    ):
        """Extract invoice data from a PDF.  When auto_save=true, also persist.
        Sync endpoint so FastAPI runs it in a threadpool (pdfplumber + SQLite are blocking).
        """
        csrf_service.verify_api_csrf(request)
        _api_rate_check(request, "invoice_extract_pdf", max_attempts=12, window=60.0)
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Solo se aceptan archivos PDF")
        max_pdf_size = 15 * 1024 * 1024
        import tempfile
        tmp_path = None
        try:
            size = 0
            chunks: list[bytes] = []
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_pdf_size:
                    raise HTTPException(status_code=400, detail="PDF demasiado grande (max 15 MB)")
                chunks.append(chunk)
            if size <= 0:
                raise HTTPException(status_code=400, detail="Archivo vacio")
            content = b"".join(chunks)
            if not content.startswith(b"%PDF"):
                raise HTTPException(status_code=400, detail="El archivo no parece ser un PDF valido")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            import pdfplumber
            text = ""
            tables: list[list] = []
            with pdfplumber.open(tmp_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
                    try:
                        for t in (page.extract_tables() or []):
                            if t:
                                tables.append(t)
                    except Exception:
                        pass
            if not text.strip():
                raise HTTPException(status_code=400, detail="No se pudo extraer texto del PDF. Puede ser un PDF escaneado (imagen).")
            # Build issuer context for tipo detection
            issuer_id = int(issuer.get("id") or 0)
            issuer_ctx: dict = {}
            if issuer_id > 0:
                from database import db_rows
                iss_rows = db_rows("SELECT razon_social, rfc FROM issuers WHERE id = ? LIMIT 1", (issuer_id,))
                issuer_ctx = dict(iss_rows[0]) if iss_rows else {}
                uid = getattr(request.state, "user_id", None)
                if uid:
                    from services.auth.users import get_user_by_id
                    u = get_user_by_id(uid)
                    if u:
                        issuer_ctx["nombre"] = u.get("name") or ""

            data = _parse_invoice_text(text, tables, issuer_context=issuer_ctx)

            if auto_save:
                if issuer_id <= 0:
                    raise HTTPException(status_code=401, detail="Sesion invalida")
                from services.invoices import foreign_invoices as fi
                fi.ensure_table()
                # Fill defaults for auto-save
                from services.invoices.exchange_rates import get_rate
                moneda = data.get("moneda") or "USD"
                tipo = data.get("tipo")
                if not tipo:
                    # Cannot auto-save without confirmed tipo; let user choose
                    return ok({**data, "auto_saved": False, "tipo_undetected": True, "needs_user_confirm": True})

                fecha = data.get("fecha") or datetime.now().strftime("%Y-%m-%d")
                period = fecha[:7] if len(fecha) >= 7 else datetime.now().strftime("%Y-%m")
                tipo_cambio = get_rate(moneda, period)
                inv_num = data.get("invoice_number") or (file.filename or "").replace(".pdf", "").replace(".PDF", "") or "PDF-IMPORT"
                empresa = data.get("empresa") or "Empresa extranjera"
                descripcion = data.get("descripcion") or (", ".join(data.get("productos") or [])[:200]) or "Invoice importado desde PDF"
                monto = data.get("monto_original") or 0
                if monto <= 0:
                    return ok({**data, "auto_saved": False, "reason": "no_amount"})
                # Deduplication check
                if fi.is_duplicate(issuer_id, inv_num, empresa):
                    return ok({**data, "auto_saved": False, "duplicate": True, "reason": "duplicate"})
                # Save PDF to storage
                archivo_rel = None
                try:
                    storage_root = os.environ.get("APP_STORAGE_PATH", "").strip() or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "storage")
                    fi_dir = os.path.join(storage_root, "foreign_invoices", str(issuer_id))
                    os.makedirs(fi_dir, exist_ok=True)
                    safe_name = re.sub(r"[^\w\-.]", "_", file.filename or "invoice.pdf")[:80]
                    dest = os.path.join(fi_dir, f"{inv_num}_{safe_name}")
                    if os.path.exists(dest):
                        # Add timestamp to avoid overwrite
                        base, ext = os.path.splitext(dest)
                        dest = f"{base}_{int(time.time())}{ext}"
                    import shutil
                    shutil.copy2(tmp_path, dest)
                    archivo_rel = os.path.relpath(dest, storage_root)
                except Exception:
                    logger.warning("Could not save foreign invoice PDF to storage", exc_info=True)
                row = fi.create(
                    issuer_id, tipo, fecha, inv_num, empresa, descripcion,
                    moneda, monto, tipo_cambio,
                    forma_pago=data.get("forma_pago"),
                    pais=data.get("pais"),
                    tax_id=data.get("tax_id"),
                    archivo=archivo_rel,
                )
                return ok({**data, "auto_saved": True, "record": row, "tipo_cambio_used": tipo_cambio})

            return ok(data)
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Error extracting invoice PDF")
            raise HTTPException(status_code=500, detail=f"Error al procesar PDF: {str(e)}")
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
