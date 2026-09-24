"""Classifies a posting's work location into Remote / a US region / Non-US /
Unknown, calibrated against real Greenhouse/Lever location strings (592
unique strings across 1783 real postings) rather than guessed.

The one real trap found in that data: "Hyderabad, IN" -- if you trust any
"City, ST" pattern as a US state code, "IN" reads as Indiana instead of
India's the country context making it obviously not. Fixed by only trusting
the state-code pattern when no known non-US city/country name is also
present in the string; an explicit "United States"/"USA"/standalone "US"
marker is checked independently and always wins regardless (so "US, Canada"
-- a real multi-location string in the data -- correctly stays a US
possibility, not a false non-US abandon).
"""

from __future__ import annotations

import re

# US Census Bureau's 4-region breakdown -- standard, not invented here.
US_STATE_REGIONS: dict[str, str] = {
    "CT": "Northeast", "ME": "Northeast", "MA": "Northeast", "NH": "Northeast",
    "RI": "Northeast", "VT": "Northeast", "NJ": "Northeast", "NY": "Northeast", "PA": "Northeast",
    "IN": "Midwest", "IL": "Midwest", "MI": "Midwest", "OH": "Midwest", "WI": "Midwest",
    "IA": "Midwest", "KS": "Midwest", "MN": "Midwest", "MO": "Midwest", "NE": "Midwest",
    "ND": "Midwest", "SD": "Midwest",
    "DE": "South", "FL": "South", "GA": "South", "MD": "South", "NC": "South", "SC": "South",
    "VA": "South", "DC": "South", "WV": "South", "AL": "South", "KY": "South", "MS": "South",
    "TN": "South", "AR": "South", "LA": "South", "OK": "South", "TX": "South",
    "AZ": "West", "CO": "West", "ID": "West", "MT": "West", "NV": "West", "NM": "West",
    "UT": "West", "WY": "West", "AK": "West", "CA": "West", "HI": "West", "OR": "West", "WA": "West",
}

# Bare city names (no state) seen in real data, plus other common ones --
# lowercase key, US state code value.
US_CITY_TO_STATE: dict[str, str] = {
    "south san francisco": "CA", "san francisco": "CA", "oakland": "CA", "los angeles": "CA",
    "bay point": "CA", "menlo park": "CA", "palo alto": "CA", "sunnyvale": "CA", "mountain view": "CA",
    "new york city": "NY", "new york": "NY",
    "seattle": "WA", "bellevue": "WA",
    "chicago": "IL",
    "austin": "TX", "houston": "TX", "dallas": "TX",
    "boston": "MA",
    "denver": "CO",
    "atlanta": "GA", "morrow": "GA",
    "miami": "FL",
    "tempe": "AZ", "phoenix": "AZ", "mesa": "AZ",
    "indianapolis": "IN",
    "columbia": "SC",
    "lexington": "KY",
    "harrisburg": "PA",
    "akron": "OH",
    "washington, d.c.": "DC", "washington dc": "DC", "washington, dc": "DC", "washington d.c.": "DC",
    "maryland": "MD", "virginia": "VA",
}
# Common shorthand codes -- checked as whole words only (word-boundary
# regex), since e.g. "la" is a real risk of colliding with ordinary text.
US_CITY_SHORTHAND: dict[str, str] = {"nyc": "NY", "sf": "CA", "sea": "WA", "chi": "IL", "atl": "GA"}

# Country/city names that mean "definitely not the US" -- checked as plain
# substrings, deliberately including common non-US cities that could
# otherwise collide with a US state code (Hyderabad/Bengaluru vs "IN").
# Calibrated against real data twice: the first pass missed Taiwan, UAE,
# the Philippines, Scandinavia, and others entirely (they fell into
# "Unknown" instead of "Non-US") -- expanded after checking what showed up
# in the real "Unknown" bucket, plus a few more common tech hubs proactively.
NON_US_MARKERS = [
    "united kingdom", " uk", "canada", "mexico", "singapore", "australia", "ireland",
    "japan", "south korea", "korea", "brazil", "china", "india", "france", "germany",
    "poland", "norway", "netherlands", "spain", "italy", "switzerland", "lithuania",
    "dublin", "london", "toronto", "vancouver", "sydney", "melbourne", "tokyo", "seoul",
    "bengaluru", "bangalore", "gurugram", "hyderabad", "warsaw", "mexico city", "paris",
    "berlin", "amsterdam", "oslo", "vilnius",
    "taiwan", "taipei", "uae", "dubai", "philippines", "manila", "luxembourg",
    "denmark", "copenhagen", "sweden", "stockholm", "munich", "vietnam",
    "portugal", "lisbon", "austria", "vienna", "belgium", "brussels",
    "finland", "helsinki", "israel", "tel aviv", "hong kong", "egypt", "cairo",
    "south africa", "new zealand", "auckland", "wellington", "argentina",
    "colombia", "chile", "peru", "bogota", "buenos aires", "romania", "bucharest",
    "united arab emirates", "thailand", "bangkok", "barcelona", "madrid",
    "slovenia", "ljubljana", "milan", "reykjavik", "reykjavík", "sao paulo", "são paulo",
]

_EXPLICIT_US_RE = re.compile(r"\b(united states|usa|u\.s\.a?\.?)\b", re.IGNORECASE)
_US_TOKEN_RE = re.compile(r"(?<![a-zA-Z])us(?![a-zA-Z])", re.IGNORECASE)
_STATE_CODE_RE = re.compile(r",\s*([A-Za-z]{2})\b")
_REMOTE_RE = re.compile(r"\bremote\b", re.IGNORECASE)
_SHORTHAND_RE = {code: re.compile(rf"(?<![a-zA-Z]){code}(?![a-zA-Z])", re.IGNORECASE) for code in US_CITY_SHORTHAND}


def classify_location(location_text: str, blurb: str = "") -> tuple[str, bool]:
    """Returns (label, should_abandon).

    label is one of: "Remote", "Northeast", "Midwest", "South", "West",
    "US - Unspecified", "Non-US", "Unknown".

    should_abandon is True only for "Non-US" -- "Unknown" (not enough
    signal either way) is deliberately left for you to review rather than
    guessed at, same "don't guess wrong" rule as everywhere else here.
    """
    text = f"{location_text} {blurb}".strip()
    if not text or text.strip().upper() in ("N/A", "NA", ""):
        return "Unknown", False
    text_lower = text.lower()

    has_non_us_marker = any(m in text_lower for m in NON_US_MARKERS)
    has_explicit_us = bool(_EXPLICIT_US_RE.search(text)) or bool(_US_TOKEN_RE.search(text))
    is_remote = bool(_REMOTE_RE.search(text))

    city_state = None
    for city, state in US_CITY_TO_STATE.items():
        if city in text_lower:
            city_state = state
            break
    if city_state is None:
        for code, pattern in _SHORTHAND_RE.items():
            if pattern.search(text):
                city_state = US_CITY_SHORTHAND[code]
                break

    # Only trust a "City, ST" state-code match when no non-US marker is
    # also present -- otherwise "Hyderabad, IN" misreads India as Indiana.
    state_code = None
    if not has_non_us_marker:
        m = _STATE_CODE_RE.search(text)
        if m and m.group(1).upper() in US_STATE_REGIONS:
            state_code = m.group(1).upper()

    has_us_signal = has_explicit_us or city_state is not None or state_code is not None

    if has_non_us_marker and not has_us_signal:
        return "Non-US", True

    if is_remote:
        return "Remote", False

    resolved_state = state_code or city_state
    if resolved_state:
        return US_STATE_REGIONS.get(resolved_state, "US - Unspecified"), False

    if has_us_signal:
        return "US - Unspecified", False

    return "Unknown", False
