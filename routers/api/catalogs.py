"""Catalogs API routes."""
import logging

from fastapi import HTTPException, Query

from database import list_catalog, search_catalog

logger = logging.getLogger(__name__)

try:
    from cfdi_pdf import CLAVE_UNIDAD, FORMA_PAGO, MONEDA, REGIMEN_FISCAL, USO_CFDI
except Exception:
    USO_CFDI = {"G03": "Gastos en general", "G01": "Adquisición de mercancías", "CN01": "Nómina"}
    REGIMEN_FISCAL = {"601": "General de Ley Personas Morales", "612": "Personas Físicas con Actividades Empresariales", "616": "Sin obligaciones fiscales", "626": "Régimen Simplificado de Confianza"}
    FORMA_PAGO = {"03": "Transferencia electrónica", "01": "Efectivo", "99": "Por definir"}
    MONEDA = {"MXN": "Peso Mexicano", "USD": "Dólar Americano"}
    CLAVE_UNIDAD = {"E48": "Unidad de servicio", "EA": "Cada uno", "H87": "Pieza"}

from routers.api._helpers import (
    MONEDA_FALLBACK,
    PRODSERV_FALLBACK,
    UNIDAD_FALLBACK,
    _catalog_list,
)
from services.http import ok


def register_catalogs_routes(router):
    """Register Catalogs routes on the API router."""

    @router.get("/catalogs/forma_pago")
    def api_forma_pago():
        try:
            return ok(list_catalog("cfdi_40_formas_pago"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid catalog table")
        except Exception:
            logger.warning("api catalogs forma_pago: usando fallback (catalogs.db no disponible)")
            return ok(_catalog_list(FORMA_PAGO))


    @router.get("/catalogs/metodo_pago")
    def api_metodo_pago():
        try:
            return ok(list_catalog("cfdi_40_metodos_pago"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid catalog table")
        except Exception:
            return ok([{"key": "PUE", "label": "Pago en una sola exhibición"}, {"key": "PPD", "label": "Pago en parcialidades o diferido"}])


    @router.get("/catalogs/uso_cfdi")
    def api_uso_cfdi():
        try:
            return ok(list_catalog("cfdi_40_usos_cfdi"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid catalog table")
        except Exception:
            logger.warning("api catalogs uso_cfdi: usando fallback (catalogs.db no disponible)")
            return ok(_catalog_list(USO_CFDI))


    @router.get("/catalogs/regimen_fiscal")
    def api_regimen_fiscal():
        try:
            return ok(list_catalog("cfdi_40_regimenes_fiscales"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid catalog table")
        except Exception:
            logger.warning("api catalogs regimen_fiscal: usando fallback (catalogs.db no disponible)")
            reg = dict(REGIMEN_FISCAL)
            reg["616"] = "Sin obligaciones fiscales"
            return ok(_catalog_list(reg))


    @router.get("/catalogs/moneda")
    def api_moneda():
        try:
            return ok(list_catalog("cfdi_40_monedas"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid catalog table")
        except Exception:
            logger.warning("api catalogs moneda: usando fallback (catalogs.db no disponible)")
            return ok(_catalog_list(MONEDA_FALLBACK))


    @router.get("/catalogs/prodserv")
    def api_prodserv(q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=50)):
        try:
            return ok(search_catalog("cfdi_40_productos_servicios", q=q, limit=limit))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid catalog table")
        except Exception:
            logger.warning("api catalogs prodserv: usando fallback estático (catalogs.db no disponible)")
            q_lower = q.strip().lower()
            out = []
            for clave, desc in PRODSERV_FALLBACK:
                if q_lower in clave or q_lower in desc.lower():
                    out.append({"key": clave, "label": desc})
                    if len(out) >= limit:
                        break
            return ok(out)


    @router.get("/catalogs/unidad")
    def api_unidad(q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=50)):
        try:
            return ok(search_catalog("cfdi_40_claves_unidades", q=q, limit=limit))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid catalog table")
        except Exception:
            logger.warning("api catalogs unidad: usando fallback (catalogs.db no disponible)")
            q_lower = q.strip().lower()
            items = [
                {"key": k, "label": v}
                for k, v in UNIDAD_FALLBACK.items()
                if q_lower in v.lower() or q_lower in k.lower()
            ]
            return ok(items[: int(limit)])


    # ---------- Month Close API ----------

