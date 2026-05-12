from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass

from config import SESSION_SECRET

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
except Exception as e:  # pragma: no cover
    # El módulo existe para prod; en entornos sin dependencia instalada, fallará al usarlo.
    AESGCM = None  # type: ignore
    HKDF = None  # type: ignore
    hashes = None  # type: ignore
    _IMPORT_ERROR = e
else:
    _IMPORT_ERROR = None


ENV_MASTER_KEY = "AT_REST_MASTER_KEY"


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    s = (s or "").strip()
    pad = "=" * ((4 - (len(s) % 4)) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _require_crypto() -> None:
    if _IMPORT_ERROR is not None or AESGCM is None or HKDF is None:
        raise RuntimeError(
            "Falta dependencia 'cryptography' para cifrado at-rest. "
            "Instala requirements.txt y reinicia."
        )


def _load_master_key() -> bytes:
    """
    Clave maestra (32 bytes).
    - Preferir env `AT_REST_MASTER_KEY` (base64url o hex).
    - Fallback seguro: derivar de SESSION_SECRET (prod ya lo exige en env).
    """
    raw = (os.getenv(ENV_MASTER_KEY) or "").strip()
    if raw:
        # Hex 64 chars
        if len(raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw):
            key = bytes.fromhex(raw)
        else:
            key = _b64d(raw)
        if len(key) != 32:
            raise ValueError(f"{ENV_MASTER_KEY} debe decodificar a 32 bytes")
        return key
    # Fallback: SESSION_SECRET (hex) -> SHA256 -> 32 bytes
    return hashlib.sha256(SESSION_SECRET.encode("utf-8")).digest()


def derive_issuer_key(issuer_id: int) -> bytes:
    _require_crypto()
    master = _load_master_key()
    info = f"issuer:{int(issuer_id)}".encode("utf-8")
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"contaneta:at-rest:v1",
        info=info,
    )
    return hkdf.derive(master)


@dataclass(frozen=True)
class EncryptedBlob:
    version: str
    nonce_b64: str
    ct_b64: str

    def to_token(self) -> str:
        return f"enc:{self.version}:{self.nonce_b64}.{self.ct_b64}"

    @staticmethod
    def from_token(token: str) -> "EncryptedBlob":
        t = (token or "").strip()
        if not t.startswith("enc:"):
            raise ValueError("token no cifrado")
        # enc:v1:<nonce>.<ct>
        parts = t.split(":", 2)
        if len(parts) != 3:
            raise ValueError("token inválido")
        _enc, ver, rest = parts
        if "." not in rest:
            raise ValueError("token inválido")
        nonce_b64, ct_b64 = rest.split(".", 1)
        if not ver:
            raise ValueError("token inválido")
        return EncryptedBlob(version=ver, nonce_b64=nonce_b64, ct_b64=ct_b64)


def encrypt_bytes(*, issuer_id: int, plaintext: bytes, aad: bytes | None = None) -> bytes:
    _require_crypto()
    key = derive_issuer_key(int(issuer_id))
    aes = AESGCM(key)
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, plaintext, aad)
    return b"CNENC1" + nonce + ct


def decrypt_bytes(*, issuer_id: int, blob: bytes, aad: bytes | None = None) -> bytes:
    _require_crypto()
    if not blob or len(blob) < 6 + 12 + 16:
        raise ValueError("blob inválido")
    if not blob.startswith(b"CNENC1"):
        raise ValueError("blob no cifrado")
    nonce = blob[6:18]
    ct = blob[18:]
    key = derive_issuer_key(int(issuer_id))
    aes = AESGCM(key)
    return aes.decrypt(nonce, ct, aad)


def encrypt_text(*, issuer_id: int, plaintext: str) -> str:
    _require_crypto()
    b = plaintext.encode("utf-8")
    key = derive_issuer_key(int(issuer_id))
    aes = AESGCM(key)
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, b, None)
    blob = EncryptedBlob(version="v1", nonce_b64=_b64e(nonce), ct_b64=_b64e(ct))
    return blob.to_token()


def decrypt_text(*, issuer_id: int, token: str) -> str:
    _require_crypto()
    blob = EncryptedBlob.from_token(token)
    if blob.version != "v1":
        raise ValueError("versión no soportada")
    nonce = _b64d(blob.nonce_b64)
    ct = _b64d(blob.ct_b64)
    key = derive_issuer_key(int(issuer_id))
    aes = AESGCM(key)
    pt = aes.decrypt(nonce, ct, None)
    return pt.decode("utf-8", errors="strict")

