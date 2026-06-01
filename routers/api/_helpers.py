"""Shared helpers for API route modules."""
import json
import logging
import os

from fastapi import HTTPException, Request

from config import BASE_DIR, DEV_FIXTURES
from database import list_catalog
from services.auth.rate_limit import is_rate_limited
from services.sat.sat_sync import get_month_totals as _get_month_totals_raw

logger = logging.getLogger(__name__)

QUOTATION_STATUSES = ("draft", "sent", "accepted", "rejected", "converted", "expired")

# Paginación: nunca devolver miles de filas; siempre limit/offset con tope
DEFAULT_LIST_LIMIT = 200
MAX_LIST_LIMIT = 500
MAX_LIST_OFFSET = 50_000


def _api_rate_check(request: Request, key: str, *, max_attempts: int = 10, window: float = 60.0):
    """Raise 429 if rate limited."""
    if is_rate_limited(request, key, max_attempts=max_attempts, window_seconds=window):
        raise HTTPException(status_code=429, detail="Demasiadas solicitudes. Intenta en un momento.")


def _load_fixture(name: str):
    """Si DEV_FIXTURES está activo, carga JSON desde tests/manual_fixtures/{name}.json."""
    if not DEV_FIXTURES:
        return None
    path = os.path.join(BASE_DIR, "tests", "manual_fixtures", f"{name}.json")
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.debug("Fixture %s: %s", name, e)
    return None


def _catalog_list(d):
    """Convierte dict {clave: etiqueta} a lista [{key, label}] para los selects."""
    return [{"key": str(k), "label": str(v)} for k, v in sorted(d.items())]


MONEDA_FALLBACK = {
    "MXN": "Peso Mexicano",
    "USD": "Dólar Americano",
    "EUR": "Euro",
    "MXV": "México Unidad de Inversión (UDI)",
    "GBP": "Libra Esterlina",
    "CAD": "Dólar Canadiense",
    "CHF": "Franco Suizo",
    "JPY": "Yen Japonés",
    "CNY": "Yuan Chino",
    "AUD": "Dólar Australiano",
    "BRL": "Real Brasileño",
    "COP": "Peso Colombiano",
    "ARS": "Peso Argentino",
    "CLP": "Peso Chileno",
    "PEN": "Sol Peruano",
    "XXX": "Los códigos asignados para transacciones en que intervenga ninguna moneda",
}

UNIDAD_FALLBACK = {
    "E48": "Unidad de servicio",
    "EA": "Cada uno",
    "H87": "Pieza",
    "ACT": "Actividad",
    "LTR": "Litro",
    "MTR": "Metro",
    "KGM": "Kilogramo",
    "GRM": "Gramo",
    "MTK": "Metro cuadrado",
    "MTQ": "Metro cúbico",
    "DAY": "Día",
    "HUR": "Hora",
    "MIN": "Minuto",
    "C62": "Unidad",
    "XBX": "Caja",
    "PA": "Paquete",
    "PK": "Paquete",
    "SET": "Conjunto",
    "PR": "Par",
    "NIU": "Número de artículos",
    "DZN": "Docena",
    "XPK": "Paquete",
    "XRO": "Rollo",
    "XCT": "Ciento",
    "XPL": "Pliego",
    "XNA": "Artículo",
    "XNE": "Kilo neto",
    "XBR": "Barra",
    "XBO": "Botella",
    "XBE": "Lata",
    "XBG": "Bolsa",
}

PRODSERV_FALLBACK = [
    ("81112100", "Servicios de asesoría en negocios y comercio"),
    ("81112101", "Asesoría en negocios"),
    ("84111500", "Servicios contables (honorarios contables)"),
    ("84111501", "Servicios de contabilidad"),
    ("84111502", "Servicios de auditoría"),
    ("84111503", "Servicios de teneduría de libros"),
    ("84111600", "Servicios de impuestos"),
    ("84111800", "Servicios de consultoría en gestión"),
    ("53111500", "Servicios de alquiler o arrendamiento de equipo"),
    ("53111501", "Renta de equipo"),
    ("53111502", "Arrendamiento de maquinaria"),
    ("53131600", "Servicios de mantenimiento de equipo"),
    ("80101600", "Servicios de consultoría en negocios"),
    ("80101601", "Consultoría administrativa"),
    ("80101602", "Consultoría en gestión"),
    ("80101800", "Servicios de consultoría en tecnología"),
    ("80101801", "Consultoría en sistemas"),
    ("81101500", "Servicios de diseño"),
    ("81101501", "Diseño gráfico"),
    ("81101502", "Diseño de software"),
    ("81102200", "Servicios de desarrollo de software"),
    ("81102201", "Desarrollo de aplicaciones"),
    ("81111800", "Servicios de soporte técnico"),
    ("81112200", "Servicios de consultoría en ingeniería"),
    ("90101500", "Servicios de limpieza"),
    ("90101600", "Servicios de limpieza de edificios"),
    ("92111500", "Servicios de capacitación"),
    ("92111501", "Capacitación empresarial"),
    ("92111502", "Cursos de capacitación"),
    ("93101600", "Servicios de publicidad"),
    ("93101601", "Publicidad y promoción"),
    ("84111801", "Servicios de consultoría en recursos humanos"),
    ("84111802", "Outsourcing o subcontratación de servicios"),
    ("81112102", "Asesoría en comercio"),
    ("43211500", "Equipo de cómputo"),
    ("43211501", "Computadoras personales"),
    ("43222600", "Software"),
    ("43222601", "Software de aplicación"),
    ("44111500", "Mobiliario de oficina"),
    ("44111501", "Escritorios y mesas"),
    ("50192100", "Servicios de mensajería"),
    ("50192101", "Mensajería y paquetería"),
]


try:
    from cfdi_pdf import FORMA_PAGO, REGIMEN_FISCAL, USO_CFDI
except Exception:
    USO_CFDI = {"G03": "Gastos en general", "G01": "Adquisición de mercancías", "CN01": "Nómina"}
    REGIMEN_FISCAL = {"601": "General de Ley Personas Morales", "612": "Personas Físicas con Actividades Empresariales", "616": "Sin obligaciones fiscales", "626": "Régimen Simplificado de Confianza"}
    FORMA_PAGO = {"03": "Transferencia electrónica", "01": "Efectivo", "99": "Por definir"}


def _load_bootstrap_catalogs() -> dict:
    """Load SAT catalogs for quick-invoice bootstrap. Shared by invoices.py and products.py."""
    catalogs = {}
    try:
        catalogs["regimen_fiscal"] = list_catalog("cfdi_40_regimenes_fiscales")
    except Exception:
        reg = dict(REGIMEN_FISCAL)
        reg.setdefault("616", "Sin obligaciones fiscales")
        catalogs["regimen_fiscal"] = _catalog_list(reg)
    try:
        catalogs["uso_cfdi"] = list_catalog("cfdi_40_usos_cfdi")
    except Exception:
        catalogs["uso_cfdi"] = _catalog_list(USO_CFDI)
    try:
        catalogs["forma_pago"] = list_catalog("cfdi_40_formas_pago")
    except Exception:
        catalogs["forma_pago"] = _catalog_list(FORMA_PAGO)
    try:
        catalogs["metodo_pago"] = list_catalog("cfdi_40_metodos_pago")
    except Exception:
        catalogs["metodo_pago"] = [
            {"key": "PUE", "label": "Pago en una sola exhibición"},
            {"key": "PPD", "label": "Pago en parcialidades o diferido"},
        ]
    try:
        catalogs["monedas"] = list_catalog("cfdi_40_monedas")
    except Exception:
        catalogs["monedas"] = _catalog_list(MONEDA_FALLBACK)
    return catalogs


def _get_month_totals_safe(issuer_id, ym, direction, *, conn=None):
    """Wrapper that never raises — returns zeros on error.

    Args:
        conn: Optional shared DB connection for atomic multi-call snapshots.
    """
    try:
        return _get_month_totals_raw(issuer_id, ym, direction, conn=conn)
    except Exception:
        return {"total_base": 0, "total_iva": 0, "total_retenciones": 0, "total_iva_neto": 0}
