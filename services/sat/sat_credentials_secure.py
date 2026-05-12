from __future__ import annotations

import logging
import os
import tempfile
from contextlib import contextmanager
from typing import Iterator

from config import BASE_DIR
from database import db

from services.sat.crypto_at_rest import decrypt_bytes, decrypt_text, encrypt_bytes, encrypt_text


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

