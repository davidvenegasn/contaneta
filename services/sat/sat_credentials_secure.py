from __future__ import annotations

import logging
import os
import tempfile
from contextlib import contextmanager
from typing import Iterator

from config import BASE_DIR
from database import db
from services.sat.crypto_at_rest import decrypt_bytes, decrypt_text, encrypt_bytes, encrypt_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FIEL file format validation (X.509 cert + private key)
# ---------------------------------------------------------------------------
_FIEL_INVALID_MSG = "Archivo FIEL inválido. Sube el .cer y .key originales del SAT."


def validate_fiel_cer(cer_bytes: bytes) -> None:
    """Verify that *cer_bytes* is a valid DER-encoded X.509 certificate.

    Raises ``ValueError`` with a user-facing Spanish message if it cannot be
    parsed.  SAT .cer files are DER-encoded, but we also accept PEM for
    flexibility.
    """
    from cryptography.x509 import load_der_x509_certificate, load_pem_x509_certificate

    # Try DER first (SAT standard), then PEM as fallback
    try:
        load_der_x509_certificate(cer_bytes)
        return
    except Exception:
        pass
    try:
        load_pem_x509_certificate(cer_bytes)
        return
    except Exception:
        pass
    raise ValueError(_FIEL_INVALID_MSG)


def validate_fiel_key(key_bytes: bytes) -> None:
    """Verify that *key_bytes* is a valid DER or PEM private key (RSA/DSA/EC).

    SAT .key files are typically DER-encoded PKCS#8 (encrypted or not).
    We only check that the blob looks like a valid private key structure;
    we do NOT attempt to decrypt password-protected keys here (the password
    is validated later by the PHP check_fiel script).

    Raises ``ValueError`` with a user-facing Spanish message if it cannot be
    parsed as any known private key format.
    """
    from cryptography.hazmat.primitives.serialization import (
        load_der_private_key,
        load_pem_private_key,
    )

    # Unencrypted DER
    try:
        load_der_private_key(key_bytes, password=None)
        return
    except (TypeError, ValueError, Exception):
        pass

    # Unencrypted PEM
    try:
        load_pem_private_key(key_bytes, password=None)
        return
    except (TypeError, ValueError, Exception):
        pass

    # For encrypted keys: we can't validate without the password, but we can
    # at least check the DER structure is plausible.  PKCS#8 encrypted keys
    # start with a SEQUENCE tag (0x30).  SAT .key files are always
    # DER-encoded PKCS#8.
    if key_bytes and key_bytes[0:1] == b'\x30' and len(key_bytes) >= 64:
        # Looks like a DER-encoded structure (SEQUENCE tag). Accept it --
        # full decryption check happens in check_fiel.php with the password.
        return

    # PEM encrypted keys start with "-----BEGIN ENCRYPTED PRIVATE KEY-----"
    if key_bytes and b"BEGIN ENCRYPTED PRIVATE KEY" in key_bytes:
        return

    raise ValueError(_FIEL_INVALID_MSG)


def _abs_under_base(path_like: str) -> str:
    p = (path_like or "").strip()
    if not p:
        raise ValueError("Ruta vacía")
    if not os.path.isabs(p):
        p = os.path.join(BASE_DIR, p)
    return os.path.normpath(os.path.abspath(p))


def _read_sat_credentials_row(issuer_id: int) -> dict | None:
    conn = db()
    try:
        row = conn.execute(
            "SELECT issuer_id, fiel_cer_path, fiel_key_path, fiel_key_password FROM sat_credentials WHERE issuer_id = ? LIMIT 1",
            (int(issuer_id),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def ensure_fiel_encrypted(issuer_id: int) -> None:
    """
    Migración lazy:
    - Si los archivos son plaintext (fiel.cer / fiel.key), crea .enc, borra originales, actualiza DB.
    - Si la contraseña no está cifrada (no empieza con 'enc:'), la cifra y actualiza DB.
    """
    row = _read_sat_credentials_row(int(issuer_id))
    if not row:
        return

    cer_rel = (row.get("fiel_cer_path") or "").strip()
    key_rel = (row.get("fiel_key_path") or "").strip()
    pwd = row.get("fiel_key_password") or ""

    needs_update = False

    # Password
    if isinstance(pwd, str) and pwd and not pwd.startswith("enc:"):
        pwd_enc = encrypt_text(issuer_id=int(issuer_id), plaintext=pwd)
        row["fiel_key_password"] = pwd_enc
        needs_update = True

    # Files
    def _enc_path(rel_path: str) -> str:
        if rel_path.endswith(".enc"):
            return rel_path
        return rel_path + ".enc"

    cer_abs = _abs_under_base(cer_rel) if cer_rel else ""
    key_abs = _abs_under_base(key_rel) if key_rel else ""

    # Si ya están cifrados por extensión, no tocamos.
    if cer_rel and not cer_rel.endswith(".enc") and os.path.isfile(cer_abs):
        with open(cer_abs, "rb") as f:
            cer_pt = f.read()
        cer_blob = encrypt_bytes(issuer_id=int(issuer_id), plaintext=cer_pt, aad=b"fiel.cer")
        cer_rel_enc = _enc_path(cer_rel)
        cer_abs_enc = _abs_under_base(cer_rel_enc)
        os.makedirs(os.path.dirname(cer_abs_enc), exist_ok=True)
        with open(cer_abs_enc, "wb") as f:
            f.write(cer_blob)
        os.chmod(cer_abs_enc, 0o600)
        try:
            os.remove(cer_abs)
        except Exception as e:
            logging.getLogger(__name__).warning("Failed to remove plaintext FIEL .cer at %s: %s", cer_abs, e)
        row["fiel_cer_path"] = cer_rel_enc
        needs_update = True

    if key_rel and not key_rel.endswith(".enc") and os.path.isfile(key_abs):
        with open(key_abs, "rb") as f:
            key_pt = f.read()
        key_blob = encrypt_bytes(issuer_id=int(issuer_id), plaintext=key_pt, aad=b"fiel.key")
        key_rel_enc = _enc_path(key_rel)
        key_abs_enc = _abs_under_base(key_rel_enc)
        os.makedirs(os.path.dirname(key_abs_enc), exist_ok=True)
        with open(key_abs_enc, "wb") as f:
            f.write(key_blob)
        os.chmod(key_abs_enc, 0o600)
        try:
            os.remove(key_abs)
        except Exception as e:
            logging.getLogger(__name__).warning("Failed to remove plaintext FIEL .key at %s: %s", key_abs, e)
        row["fiel_key_path"] = key_rel_enc
        needs_update = True

    if not needs_update:
        return

    conn = db()
    try:
        conn.execute(
            """
            UPDATE sat_credentials
            SET fiel_cer_path = ?, fiel_key_path = ?, fiel_key_password = ?, updated_at = datetime('now')
            WHERE issuer_id = ?
            """,
            (
                (row.get("fiel_cer_path") or "").strip(),
                (row.get("fiel_key_path") or "").strip(),
                row.get("fiel_key_password") or "",
                int(issuer_id),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _decrypt_password(issuer_id: int, stored: str) -> str:
    s = (stored or "")
    if not s:
        return ""
    if s.startswith("enc:"):
        return decrypt_text(issuer_id=int(issuer_id), token=s)
    return s


def _decrypt_file_to_temp(issuer_id: int, rel_path: str, *, aad: bytes) -> str:
    abs_path = _abs_under_base(rel_path)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(abs_path)
    if not rel_path.endswith(".enc"):
        # plaintext file
        return abs_path
    with open(abs_path, "rb") as f:
        blob = f.read()
    pt = decrypt_bytes(issuer_id=int(issuer_id), blob=blob, aad=aad)
    fd, out_path = tempfile.mkstemp(prefix=f"fiel_{issuer_id}_", suffix=".bin")
    os.close(fd)
    with open(out_path, "wb") as f:
        f.write(pt)
    os.chmod(out_path, 0o600)
    return out_path


def extract_fiel_subject(issuer_id: int) -> dict:
    """Extract RFC and razón social from the issuer's stored FIEL certificate.

    Reads the encrypted-at-rest .cer file, decrypts to memory, parses with
    cryptography.x509, and pulls the Mexican SAT-relevant subject attributes:
      - RFC: from serialNumber attribute (OID 2.5.4.5). SAT format is usually
        "RFC / CURP" for personas físicas or just "RFC" for personas morales.
      - nombre: from commonName (CN, OID 2.5.4.3) — razón social or full name.

    Returns an empty dict if no credentials configured or parsing fails. Never
    raises; this is best-effort metadata used as form defaults.
    """
    try:
        ensure_fiel_encrypted(int(issuer_id))
        row = _read_sat_credentials_row(int(issuer_id))
        if not row:
            return {}
        cer_rel = (row.get("fiel_cer_path") or "").strip()
        if not cer_rel:
            return {}
        abs_path = _abs_under_base(cer_rel)
        with open(abs_path, "rb") as f:
            blob = f.read()
        try:
            cer_bytes = decrypt_bytes(blob, aad=b"fiel.cer")
        except Exception:
            cer_bytes = blob  # not encrypted yet
        from cryptography.x509 import load_der_x509_certificate, load_pem_x509_certificate
        from cryptography.x509.oid import NameOID
        cert = None
        for loader in (load_der_x509_certificate, load_pem_x509_certificate):
            try:
                cert = loader(cer_bytes)
                break
            except Exception:
                continue
        if cert is None:
            return {}
        out: dict = {}
        for attr in cert.subject:
            if attr.oid == NameOID.SERIAL_NUMBER:
                raw = (attr.value or "").strip()
                rfc = raw.split("/")[0].strip().upper()
                if rfc:
                    out["rfc"] = rfc
            elif attr.oid == NameOID.COMMON_NAME:
                out["nombre"] = (attr.value or "").strip()
        # Certificate expiry
        from datetime import datetime, timezone
        try:
            expires_utc = cert.not_valid_after_utc
        except AttributeError:
            expires_utc = cert.not_valid_after.replace(tzinfo=timezone.utc)
        out["expires_at"] = expires_utc.isoformat()
        out["days_until_expiry"] = (expires_utc - datetime.now(timezone.utc)).days
        return out
    except Exception as e:
        logger.warning("extract_fiel_subject failed for issuer %s: %s", issuer_id, e)
        return {}


@contextmanager
def decrypted_fiel_env(issuer_id: int) -> Iterator[dict[str, str]]:
    """
    Crea archivos temporales con CER/KEY (plaintext) + password plaintext.
    Devuelve un dict de env vars para pasar a procesos (PHP).
    Limpia los temporales al final.
    """
    ensure_fiel_encrypted(int(issuer_id))
    row = _read_sat_credentials_row(int(issuer_id))
    if not row:
        raise ValueError("No hay sat_credentials para el issuer")

    cer_rel = (row.get("fiel_cer_path") or "").strip()
    key_rel = (row.get("fiel_key_path") or "").strip()
    pwd_stored = row.get("fiel_key_password") or ""

    if not cer_rel or not key_rel:
        raise ValueError("Faltan rutas de CER/KEY en sat_credentials")

    tmp_paths: list[str] = []
    cer_tmp = _decrypt_file_to_temp(int(issuer_id), cer_rel, aad=b"fiel.cer")
    key_tmp = _decrypt_file_to_temp(int(issuer_id), key_rel, aad=b"fiel.key")
    if cer_tmp != _abs_under_base(cer_rel):
        tmp_paths.append(cer_tmp)
    if key_tmp != _abs_under_base(key_rel):
        tmp_paths.append(key_tmp)
    pwd_plain = _decrypt_password(int(issuer_id), str(pwd_stored))

    env = {
        "SAT_FIEL_CER_PATH": cer_tmp,
        "SAT_FIEL_KEY_PATH": key_tmp,
        "SAT_FIEL_PASSWORD": pwd_plain,
    }
    try:
        yield env
    finally:
        for p in tmp_paths:
            try:
                os.remove(p)
            except Exception:
                pass

