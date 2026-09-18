"""PII masking for anything written to disk under evidence/ or
escalation/requests/ (spec §9: raw member IDs/balances are never written
in full to logs or artifacts; full values exist only in memory during a
run). Shared by both agent/discover.py and replay/engine.py so the two
don't drift into different redaction rules.
"""

from __future__ import annotations

import re


def mask(value) -> str:
    text = str(value)
    if len(text) <= 4:
        return "*" * len(text)
    return "*" * (len(text) - 4) + text[-4:]


def mask_url(url: str) -> str:
    """Masks member-ID-shaped path segments (4+ digit runs bounded by
    '/') in a URL, e.g. 'http://127.0.0.1:5000/members/10001' ->
    'http://127.0.0.1:5000/members/*0001'. Leaves the host:port alone --
    the lookbehind/lookahead only match digit runs that are themselves a
    full path segment, not a port number after ':'."""

    def _mask_segment(match: re.Match) -> str:
        return mask(match.group())

    return re.sub(r"(?<=/)\d{4,}(?=/|$|\?)", _mask_segment, url)
