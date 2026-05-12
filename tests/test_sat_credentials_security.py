"""SAT credentials security tests — verify encryption at rest works correctly."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_sat_sec_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-sat-sec"

from services.sat.crypto_at_rest import decrypt_bytes, encrypt_bytes


def test_encrypted_blob_does_not_contain_plaintext():
    """Encrypted credential blob must NOT contain the original plaintext."""
    plaintext = b"PRIVATE KEY DATA - THIS IS SECRET"
    encrypted = encrypt_bytes(issuer_id=9999, plaintext=plaintext, aad=b"fiel.key")

    assert plaintext not in encrypted, "Encrypted blob contains plaintext!"
    assert len(encrypted) > len(plaintext)


def test_wrong_key_fails_decrypt():
    """Decryption with tampered blob must fail cleanly."""
    plaintext = b"SECRET FIEL CONTENT"
    encrypted = encrypt_bytes(issuer_id=9998, plaintext=plaintext, aad=b"fiel.cer")

    tampered = bytearray(encrypted)
    if len(tampered) > 15:
        tampered[14] ^= 0xFF
    tampered = bytes(tampered)

    with pytest.raises(Exception):
        decrypt_bytes(issuer_id=9998, blob=tampered, aad=b"fiel.cer")


def test_encrypt_decrypt_roundtrip():
    """Encrypt then decrypt should return original plaintext."""
    plaintext = b"Test FIEL certificate content\x00\x01\x02"
    aad = b"fiel.cer"

    encrypted = encrypt_bytes(issuer_id=9996, plaintext=plaintext, aad=aad)
    decrypted = decrypt_bytes(issuer_id=9996, blob=encrypted, aad=aad)

    assert decrypted == plaintext


def test_different_issuer_cannot_decrypt():
    """Issuer A's encrypted blob must not be decryptable by issuer B's key."""
    plaintext = b"FIEL data for issuer A only"
    encrypted = encrypt_bytes(issuer_id=9995, plaintext=plaintext, aad=b"fiel.key")

    with pytest.raises(Exception):
        decrypt_bytes(issuer_id=9994, blob=encrypted, aad=b"fiel.key")
