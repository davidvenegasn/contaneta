"""Tests for FIEL .cer/.key format validation (Phase 1 -- Security MEDIUM)."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_test_db = os.environ.get("APP_DB_PATH")
if not _test_db:
    _fd, _test_db = tempfile.mkstemp(suffix=".db", prefix="test_fiel_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _test_db
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-fiel"

import pytest
from services.sat.sat_credentials_secure import validate_fiel_cer, validate_fiel_key


def _make_self_signed_cert_der():
    """Generate a self-signed X.509 certificate (DER) and its private key (DER)."""
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    import datetime as dt

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "MX"),
        x509.NameAttribute(NameOID.COMMON_NAME, "Test FIEL"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(dt.datetime.now(dt.timezone.utc))
        .not_valid_after(dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    cer_der = cert.public_bytes(serialization.Encoding.DER)
    key_der = key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return cer_der, key_der


class TestValidateFielCer:
    def test_valid_der_cert_passes(self):
        cer_der, _ = _make_self_signed_cert_der()
        # Should not raise
        validate_fiel_cer(cer_der)

    def test_valid_pem_cert_passes(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.x509 import load_der_x509_certificate
        cer_der, _ = _make_self_signed_cert_der()
        cert = load_der_x509_certificate(cer_der)
        cer_pem = cert.public_bytes(serialization.Encoding.PEM)
        validate_fiel_cer(cer_pem)

    def test_txt_file_as_cer_fails(self):
        with pytest.raises(ValueError, match="FIEL inválido"):
            validate_fiel_cer(b"This is not a certificate, just a text file.")

    def test_empty_bytes_fails(self):
        with pytest.raises(ValueError, match="FIEL inválido"):
            validate_fiel_cer(b"")

    def test_random_binary_fails(self):
        with pytest.raises(ValueError, match="FIEL inválido"):
            validate_fiel_cer(os.urandom(1024))


class TestValidateFielKey:
    def test_valid_der_key_passes(self):
        _, key_der = _make_self_signed_cert_der()
        validate_fiel_key(key_der)

    def test_valid_pem_key_passes(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key_pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        validate_fiel_key(key_pem)

    def test_txt_file_as_key_fails(self):
        with pytest.raises(ValueError, match="FIEL inválido"):
            validate_fiel_key(b"This is not a key file at all.")

    def test_empty_bytes_fails(self):
        with pytest.raises(ValueError, match="FIEL inválido"):
            validate_fiel_key(b"")

    def test_encrypted_der_key_accepted(self):
        """SAT .key files are often encrypted PKCS#8 (DER). They start with 0x30 SEQUENCE tag."""
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key_enc = key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.BestAvailableEncryption(b"testpassword"),
        )
        # Encrypted DER key starts with 0x30 and should be accepted
        validate_fiel_key(key_enc)
