"""Session security tests — cookie signing, expiry, and tamper detection."""
import time

from services.auth.session import sign_session, verify_session


def test_valid_session_roundtrip():
    """Sign and verify a session cookie."""
    cookie = sign_session(user_id=1, issuer_id=2)
    result = verify_session(cookie)
    assert result is not None
    assert result[0] == 1  # user_id
    assert result[1] == 2  # issuer_id


def test_tampered_cookie_rejected():
    """Modifying the payload should fail verification."""
    import base64

    cookie = sign_session(user_id=1, issuer_id=2)
    # Decode, change user_id, re-encode (without re-signing)
    raw = base64.urlsafe_b64decode(cookie + "==").decode()
    payload, sig = raw.rsplit(".", 1)
    # Change user_id from 1 to 999
    tampered_payload = payload.replace("1|2|", "999|2|", 1)
    tampered_raw = f"{tampered_payload}.{sig}"
    tampered = base64.urlsafe_b64encode(tampered_raw.encode()).decode().rstrip("=")
    result = verify_session(tampered)
    assert result is None, "Tampered cookie should be rejected"


def test_expired_cookie_rejected():
    """Cookie with past expiry should be rejected."""
    import base64
    import hashlib
    import hmac

    from config import SESSION_SECRET

    # Create a cookie that expired 1 second ago
    expiry = int(time.time()) - 1
    payload = f"1|2|{expiry}"
    sig = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    cookie = base64.urlsafe_b64encode(f"{payload}.{sig}".encode()).decode().rstrip("=")

    result = verify_session(cookie)
    assert result is None, "Expired cookie should be rejected"


def test_wrong_secret_rejected():
    """Cookie signed with a different secret should be rejected."""
    import base64
    import hashlib
    import hmac

    wrong_secret = "totally-wrong-secret-key"
    expiry = int(time.time()) + 86400
    payload = f"1|2|{expiry}"
    sig = hmac.new(wrong_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    cookie = base64.urlsafe_b64encode(f"{payload}.{sig}".encode()).decode().rstrip("=")

    result = verify_session(cookie)
    assert result is None, "Cookie signed with wrong secret should be rejected"


def test_empty_cookie_rejected():
    assert verify_session("") is None
    assert verify_session(None) is None
    assert verify_session("   ") is None
