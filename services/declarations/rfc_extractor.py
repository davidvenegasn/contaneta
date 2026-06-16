"""Find the taxpayer's RFC inside a parsed declaration PDF."""
import re
from typing import Optional

RFC_RE = re.compile(r'\b([A-ZÑ&]{3,4}[0-9]{6}[A-Z0-9]{3})\b')

# SAT institutional RFCs to exclude
SAT_RFCS = {"SAT970701NN3"}


def find_rfc_in_pdf(text: str) -> Optional[str]:
    """Returns the most likely RFC of the taxpayer (not the SAT signing RFC).

    Strategy: look for RFC near labels "RFC", "Contribuyente", "Razon social".
    Filter out the SAT institutional RFCs.
    """
    candidates = []
    label_re = re.compile(
        r'(RFC|Contribuyente)\s*:?\s*([A-ZÑ&]{3,4}[0-9]{6}[A-Z0-9]{3})', re.I
    )
    for m in label_re.finditer(text):
        rfc = m.group(2).upper()
        if rfc not in SAT_RFCS:
            candidates.append(rfc)
    if candidates:
        return candidates[0]
    # Fallback: any RFC found, excluding SAT
    all_rfcs = [r.upper() for r in RFC_RE.findall(text) if r.upper() not in SAT_RFCS]
    return all_rfcs[0] if all_rfcs else None
