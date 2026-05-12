import json
import logging
import os
import re
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from config import BASE_DIR
from database import db

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def _storage_root_abs() -> str:
    """
    Storage root. Respeta APP_STORAGE_PATH si existe, si no usa BASE_DIR/storage.
    Esta función se usa para resolver xml_path relativos cuando storage vive fuera del proyecto.
    """
    raw = (os.environ.get("APP_STORAGE_PATH") or "").strip()
    if raw:
        root = raw if os.path.isabs(raw) else os.path.join(BASE_DIR, raw)
    else:
        root = os.path.join(BASE_DIR, "storage")
    return os.path.normpath(os.path.abspath(root))


def _resolve_xml_abs_path(xml_path: str) -> str:
    """
    Resuelve xml_path guardado en DB a ruta absoluta segura.
    Soporta:
    - Absoluta (validada bajo BASE_DIR o storage_root).
    - Relativa tipo 'storage/xml/...' (se resuelve a storage_root/xml/... si APP_STORAGE_PATH está definido).
    - Relativa genérica (se resuelve bajo BASE_DIR).
    """
    p = (xml_path or "").strip()
    if not p:
        raise ValueError("xml_path vacío")

    base_abs = os.path.normpath(os.path.abspath(BASE_DIR))
    storage_abs = _storage_root_abs()

    def _check_under(root_abs: str, candidate: str) -> str:
        root_abs = os.path.normpath(os.path.abspath(root_abs))
        abs_p = os.path.normpath(os.path.abspath(candidate))
        if abs_p == root_abs:
            return abs_p
        if not abs_p.startswith(root_abs + os.sep):
            raise ValueError("Ruta XML inválida (fuera de raíz permitida)")
        return abs_p

    if os.path.isabs(p):
        # permitir rutas absolutas solo si están bajo BASE_DIR o storage_root
        try:
            return _check_under(storage_abs, p)
        except Exception:
            return _check_under(base_abs, p)

    # Caso típico: "storage/xml/..."
    if p.startswith("storage" + os.sep) or p.startswith("storage/"):
        rel = p.split("/", 1)[1] if "/" in p else p.split(os.sep, 1)[1]
        return _check_under(storage_abs, os.path.join(storage_abs, rel))

    # Fallback: relativo bajo BASE_DIR
    return _check_under(base_abs, os.path.join(base_abs, p))


def _local_name(tag: str) -> str:
    # '{ns}Tag' -> 'Tag'
    if not tag:
        return ""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _find_first(root: ET.Element, name: str) -> Optional[ET.Element]:
    """Busca el primer elemento en el árbol por local-name."""
    for el in root.iter():
        if _local_name(el.tag) == name:
            return el
    return None


def _find_all(root: ET.Element, name: str) -> list[ET.Element]:
    out: list[ET.Element] = []
    for el in root.iter():
        if _local_name(el.tag) == name:
            out.append(el)
    return out


def _norm_desc(s: str) -> str:
    """Normaliza descripción de concepto CFDI para dedup de productos.
    Quita sufijos de mes/parcialidad comunes en facturas MX:
      'Servicio X - Enero 2026 1/2' → 'Servicio X'
      'Consultoría Febrero 2026'    → 'Consultoría'
    """
    t = (s or "").strip()
    t = re.sub(r"\s+", " ", t)
    if not t:
        return t
    # Meses en español
    _meses = r"(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)"
    # Quitar separador + mes + año + parcialidad opcional: "- Enero 2026 1/2"
    t = re.sub(
        r"\s*[-–—/|,]\s*" + _meses + r"(?:\s+\d{4})?" + r"(?:\s+\d+\s*/\s*\d+)?\s*$",
        "", t, flags=re.IGNORECASE,
    )
    # Quitar mes + año sin separador al final: "Febrero 2026"
    t = re.sub(
        r"\s+" + _meses + r"\s+\d{4}" + r"(?:\s+\d+\s*/\s*\d+)?\s*$",
        "", t, flags=re.IGNORECASE,
    )
    # Quitar parcialidad huérfana: "1/2", "2/3"
    t = re.sub(r"\s*[-–—]\s*\d+\s*/\s*\d+\s*$", "", t)
    return t.strip()


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


@dataclass
class BackfillResult:
    processed: int = 0
    clients_upserted: int = 0
    observations_upserted: int = 0
    errors_count: int = 0
    errors: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


def upsert_clients_from_cfdi_xml(issuer_id: int, xml_path: str) -> int:
    """
    Extrae receptor de CFDI 4.0 y upserta en tabla clients.
    Retorna 1 si se intentó upsert (0 si no hay receptor/RFC).
    """
    abs_path = _resolve_xml_abs_path(xml_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError("XML no existe en disco")

    tree = ET.parse(abs_path)
    root = tree.getroot()

    receptor = _find_first(root, "Receptor")
    if receptor is None:
        return 0
    rfc = (receptor.attrib.get("Rfc") or "").strip().upper()
    if not rfc:
        return 0
    name = (receptor.attrib.get("Nombre") or "").strip() or None
    cp = (receptor.attrib.get("DomicilioFiscalReceptor") or "").strip() or None
    regimen = (receptor.attrib.get("RegimenFiscalReceptor") or "").strip() or None
    uso = (receptor.attrib.get("UsoCFDI") or "").strip().upper() or None

    now = _now_iso()
    conn = db()
    try:
        conn.execute(
            """
            INSERT INTO clients (
              issuer_id, rfc, name, cp, regimen_fiscal, uso_cfdi_default,
              created_at, updated_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), datetime('now'))
            ON CONFLICT(issuer_id, rfc) DO UPDATE SET
              name = COALESCE(excluded.name, clients.name),
              cp = COALESCE(excluded.cp, clients.cp),
              regimen_fiscal = COALESCE(excluded.regimen_fiscal, clients.regimen_fiscal),
              uso_cfdi_default = COALESCE(excluded.uso_cfdi_default, clients.uso_cfdi_default),
              updated_at = datetime('now'),
              last_seen_at = datetime('now')
            """,
            (issuer_id, rfc, name, cp, regimen, uso),
        )
        conn.commit()
        return 1
    finally:
        conn.close()


def upsert_product_observations_from_cfdi_xml(issuer_id: int, xml_path: str) -> int:
    """
    Extrae Conceptos/Concepto de CFDI 4.0 y upserta en product_observations.
    Retorna número de conceptos procesados (observaciones upsertadas).
    """
    abs_path = _resolve_xml_abs_path(xml_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError("XML no existe en disco")

    tree = ET.parse(abs_path)
    root = tree.getroot()
    conceptos = _find_all(root, "Concepto")
    if not conceptos:
        return 0

    # Moneda está en Comprobante
    comprobante = root if _local_name(root.tag) == "Comprobante" else _find_first(root, "Comprobante")
    moneda = (comprobante.attrib.get("Moneda") if comprobante is not None else None) or None
    moneda = (moneda or "").strip().upper() or None

    n = 0
    conn = db()
    try:
        for c in conceptos:
            clave_prod_serv = (c.attrib.get("ClaveProdServ") or "").strip() or None
            clave_unidad = (c.attrib.get("ClaveUnidad") or "").strip() or None
            unidad = (c.attrib.get("Unidad") or "").strip() or None
            raw_desc = _norm_desc(c.attrib.get("Descripcion") or "")
            if not raw_desc:
                continue
            unit_price = _to_float(c.attrib.get("ValorUnitario"))

            conn.execute(
                """
                INSERT INTO product_observations (
                  issuer_id, clave_prod_serv, clave_unidad, unidad, raw_description,
                  unit_price_hint, currency, times_seen, last_seen_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, datetime('now'), datetime('now'), datetime('now'))
                ON CONFLICT(issuer_id, clave_prod_serv, clave_unidad, raw_description) DO UPDATE SET
                  times_seen = product_observations.times_seen + 1,
                  last_seen_at = datetime('now'),
                  updated_at = datetime('now'),
                  currency = COALESCE(excluded.currency, product_observations.currency),
                  unidad = COALESCE(excluded.unidad, product_observations.unidad),
                  unit_price_hint = CASE
                    WHEN excluded.unit_price_hint IS NULL THEN product_observations.unit_price_hint
                    WHEN product_observations.unit_price_hint IS NULL THEN excluded.unit_price_hint
                    ELSE ((product_observations.unit_price_hint * product_observations.times_seen) + excluded.unit_price_hint)
                         / (product_observations.times_seen + 1)
                  END
                """,
                (issuer_id, clave_prod_serv, clave_unidad, unidad, raw_desc, unit_price, moneda),
            )
            # Auto-create confirmed product (user can edit name/price later)
            conn.execute(
                """
                INSERT INTO products (
                  issuer_id, name, clave_prod_serv, clave_unidad, unidad,
                  default_unit_price, default_currency, active,
                  created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, datetime('now'), datetime('now'))
                ON CONFLICT(issuer_id, name, clave_prod_serv, clave_unidad) DO UPDATE SET
                  unidad = COALESCE(excluded.unidad, products.unidad),
                  default_currency = COALESCE(excluded.default_currency, products.default_currency),
                  updated_at = datetime('now')
                """,
                (issuer_id, raw_desc, clave_prod_serv, clave_unidad, unidad, unit_price, moneda),
            )
            n += 1
        conn.commit()
        return n
    finally:
        conn.close()


def backfill_issuer_from_cfdi(issuer_id: int) -> bool:
    """
    Extract Emisor/@RegimenFiscal from the first issued CFDI and update the
    issuer's regimen_fiscal if it is currently NULL.
    Returns True if an update was made.
    """
    conn = db()
    try:
        issuer = conn.execute(
            "SELECT regimen_fiscal FROM issuers WHERE id = ?", (issuer_id,)
        ).fetchone()
        if not issuer:
            return False
        if issuer["regimen_fiscal"]:
            return False  # already set

        row = conn.execute(
            "SELECT xml_path FROM sat_cfdi "
            "WHERE issuer_id = ? AND direction = 'issued' "
            "AND xml_path IS NOT NULL AND TRIM(COALESCE(xml_path,'')) != '' "
            "ORDER BY COALESCE(fecha_emision,'') DESC LIMIT 1",
            (issuer_id,),
        ).fetchone()
        if not row or not row["xml_path"]:
            return False
    finally:
        conn.close()

    try:
        abs_path = _resolve_xml_abs_path(row["xml_path"])
        if not os.path.exists(abs_path):
            return False
        tree = ET.parse(abs_path)
        emisor = _find_first(tree.getroot(), "Emisor")
        if emisor is None:
            return False
        regimen = (emisor.attrib.get("RegimenFiscal") or "").strip()
        if not regimen:
            return False
    except Exception as e:
        logger.warning("backfill_issuer_from_cfdi issuer=%s err=%s", issuer_id, e)
        return False

    conn = db()
    try:
        conn.execute(
            "UPDATE issuers SET regimen_fiscal = ?, updated_at = datetime('now') "
            "WHERE id = ? AND (regimen_fiscal IS NULL OR TRIM(regimen_fiscal) = '')",
            (regimen, issuer_id),
        )
        conn.commit()
        logger.info("backfill_issuer_from_cfdi issuer=%s regimen=%s", issuer_id, regimen)
        return True
    finally:
        conn.close()


def backfill_catalog_from_existing_cfdi(
    issuer_id: int,
    *,
    limit: Optional[int] = None,
    since: Optional[str] = None,
) -> BackfillResult:
    """
    Itera CFDI emitidos existentes (sat_cfdi, direction='issued', xml_path!=NULL) y upserta:
    - clients (receptor)
    - product_observations (conceptos)

    No detiene por errores: agrega a result.errors y sigue.
    since: 'YYYY-MM-DD' o 'YYYY-MM' (se compara contra fecha_emision ISO si existe).
    """
    res = BackfillResult()
    lim = None
    if limit is not None:
        try:
            lim = int(limit)
            if lim <= 0:
                lim = None
        except Exception:
            lim = None

    since_val = (since or "").strip() or None

    where = [
        "issuer_id = ?",
        "direction = 'issued'",
        "xml_path IS NOT NULL",
        "TRIM(COALESCE(xml_path,'')) != ''",
    ]
    params: list[Any] = [issuer_id]
    if since_val:
        # fecha_emision es ISO-like en DB; si es NULL se ignora
        where.append("(fecha_emision IS NOT NULL AND fecha_emision >= ?)")
        params.append(since_val)

    sql = (
        "SELECT uuid, xml_path, fecha_emision FROM sat_cfdi "
        "WHERE " + " AND ".join(where) + " "
        "ORDER BY COALESCE(fecha_emision,'') DESC, id DESC"
    )
    if lim is not None:
        sql += " LIMIT ?"
        params.append(lim)

    conn = db()
    try:
        rows = conn.execute(sql, tuple(params)).fetchall()
    finally:
        conn.close()

    for r in rows:
        res.processed += 1
        xml_path = r["xml_path"] if r else None
        uuid = r["uuid"] if r else None
        try:
            if xml_path:
                res.clients_upserted += upsert_clients_from_cfdi_xml(issuer_id, str(xml_path))
                res.observations_upserted += upsert_product_observations_from_cfdi_xml(issuer_id, str(xml_path))
        except Exception as e:
            res.errors_count += 1
            msg = f"uuid={str(uuid or '')[:36]} err={str(e)[:200]}"
            res.errors.append(msg)
            logger.warning("backfill_catalog issuer=%s %s", issuer_id, msg, exc_info=True)
            continue

    # Auto-fill issuer régimen fiscal from first CFDI if still missing
    try:
        backfill_issuer_from_cfdi(issuer_id)
    except Exception as e:
        logger.warning("backfill_issuer_from_cfdi issuer=%s err=%s", issuer_id, e)

    return res

