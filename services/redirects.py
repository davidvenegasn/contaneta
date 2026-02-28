"""Safe redirect helpers — prevent open redirect via user-controlled 'next' params."""


def safe_next_url(next_str: str | None, default: str = "/portal/home") -> str:
    """
    Sanitize a user-supplied redirect target.

    Rules:
    - Must be a relative path starting with "/"
    - Must NOT contain "://" (blocks http://evil.com)
    - Must NOT contain backslashes (blocks \\\\evil.com on some browsers)
    - Must start with an allowed prefix (/portal, /admin, /login)
    - Returns default if input is invalid
    """
    if not next_str or not isinstance(next_str, str):
        return default

    url = next_str.strip()

    if not url.startswith("/"):
        return default

    if "://" in url:
        return default

    if "\\" in url:
        return default

    # Block protocol-relative URLs like //evil.com
    if url.startswith("//"):
        return default

    allowed_prefixes = ("/portal", "/admin", "/login", "/")
    if not any(url == prefix or url.startswith(prefix + "/") or url.startswith(prefix + "?") for prefix in allowed_prefixes):
        return default

    return url
