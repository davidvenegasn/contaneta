"""INGRESO vs GASTO detection by comparing issuer name against PDF seller/buyer sections."""
import re
import unicodedata

_BILL_TO_MARKER = re.compile(
    r"^(?:Bill\s*To|Billed?\s*To|Sold\s*To|Ship\s*To|Invoice\s*To|Purchaser|Customer|Comprador|Cliente|To:)\b",
    re.IGNORECASE,
)


def _normalize_for_match(s: str) -> str:
    """Lowercase, strip accents, strip punctuation for fuzzy name matching."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")  # strip accents
    s = re.sub(r"[^\w\s]", " ", s.lower())
    return " ".join(s.split())


def _name_words(name: str) -> list[str]:
    """Extract significant words (>= 2 chars) from a normalized name."""
    return [w for w in _normalize_for_match(name).split() if len(w) >= 2]


def _words_match(needle_words: list[str], haystack: str, min_matches: int = 2) -> bool:
    """Check if at least `min_matches` words from needle appear in haystack."""
    if not needle_words:
        return False
    hay = _normalize_for_match(haystack)
    hits = sum(1 for w in needle_words if w in hay)
    # For single-word names (e.g. "Stripe"), require just 1 match
    needed = min(min_matches, len(needle_words))
    return hits >= needed


def _detect_tipo(text: str, issuer_context: dict | None) -> str | None:
    """Detect INGRESO vs GASTO by comparing issuer name against PDF sections.

    Returns:
        "INGRESO" if the issuer appears to be the seller (name in header).
        "GASTO" if the issuer appears to be the buyer (name in bill-to section).
        None if it cannot be determined.
    """
    if not issuer_context:
        return None
    issuer_name = (
        issuer_context.get("razon_social")
        or issuer_context.get("nombre")
        or ""
    ).strip()
    if len(issuer_name) < 2:
        return None

    words = _name_words(issuer_name)
    if not words:
        return None

    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]

    # Split text into seller block (before Bill To) and buyer block (after Bill To)
    seller_lines: list[str] = []
    buyer_lines: list[str] = []
    bill_to_idx = None
    for i, line in enumerate(lines[:30]):
        if _BILL_TO_MARKER.match(line):
            bill_to_idx = i
            break
        seller_lines.append(line)

    if bill_to_idx is not None:
        # Collect buyer lines: up to 8 lines after "Bill To" marker, stop at next section
        for line in lines[bill_to_idx + 1: bill_to_idx + 9]:
            if re.match(r"^(?:Invoice|Date|Due|Terms|Payment|Amount|Total|Item|Description|#)\b", line, re.IGNORECASE):
                break
            buyer_lines.append(line)

    seller_text = " ".join(seller_lines[:10])
    buyer_text = " ".join(buyer_lines)

    in_seller = _words_match(words, seller_text)
    in_buyer = _words_match(words, buyer_text)

    if in_seller and not in_buyer:
        return "INGRESO"
    if in_buyer and not in_seller:
        return "GASTO"
    # Ambiguous or no match
    return None
