# Copyright (C) 2026 Open HamClock Backend (OHB) Contributors
# License: GNU Affero General Public License v3.0 (AGPLv3)
# See LICENSE file or <https://www.gnu.org/licenses/agpl-3.0.html>
#

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class BandInfo:
    band: int          # ClickHouse band code (-1, 0, 1, 3, 5, ..., 1296)
    frequency: int     # WSPR dial frequency in Hz
    display: str       # Display label (e.g. "LF", "MF", "160m", ..., "70cm", "23cm")
    aliases: tuple[str, ...] = ()

    @property
    def query_matches(self) -> tuple[str, ...]:
        """Values that should match this band in database queries."""
        vals = {self.display, str(self.band)}
        for a in self.aliases:
            vals.add(a)
            vals.add(a.upper())
            vals.add(a.lower())
        return tuple(vals)


# Authoritative list of all bands supported by WSPR
WSPR_BANDS: list[BandInfo] = [
    BandInfo(band=-1,   frequency=136000,     display="LF",   aliases=("2200", "2200m", "lf")),
    BandInfo(band=0,    frequency=474200,     display="MF",   aliases=("630", "630m", "mf")),
    BandInfo(band=1,    frequency=1836600,    display="160m", aliases=("160", "160m")),
    BandInfo(band=3,    frequency=3568600,    display="80m",  aliases=("80", "80m")),
    BandInfo(band=5,    frequency=5287200,    display="60m",  aliases=("60", "60m")),
    BandInfo(band=7,    frequency=7038600,    display="40m",  aliases=("40", "40m")),
    BandInfo(band=10,   frequency=10138700,   display="30m",  aliases=("30", "30m")),
    BandInfo(band=14,   frequency=14095600,   display="20m",  aliases=("20", "20m")),
    BandInfo(band=18,   frequency=18104600,   display="17m",  aliases=("17", "17m")),
    BandInfo(band=21,   frequency=21094600,   display="15m",  aliases=("15", "15m")),
    BandInfo(band=24,   frequency=24924600,   display="12m",  aliases=("12", "12m")),
    BandInfo(band=28,   frequency=28124600,   display="10m",  aliases=("10", "10m")),
    BandInfo(band=50,   frequency=50293000,   display="6m",   aliases=("6", "6m")),
    BandInfo(band=70,   frequency=70091000,   display="4m",   aliases=("4", "4m")),
    BandInfo(band=144,  frequency=144489000,  display="2m",   aliases=("2", "2m")),
    BandInfo(band=432,  frequency=432300000,  display="70cm", aliases=("70cm", "70c", "70", "432")),
    BandInfo(band=1296, frequency=1296500000, display="23cm", aliases=("23cm", "23c", "23", "1296")),
]

# Quick lookups
BAND_BY_CODE: dict[int, BandInfo] = {b.band: b for b in WSPR_BANDS}
BAND_BY_DISPLAY: dict[str, BandInfo] = {b.display.lower(): b for b in WSPR_BANDS}
BAND_BY_FREQUENCY: dict[int, BandInfo] = {b.frequency: b for b in WSPR_BANDS}

# Lookup by any alias, display name, or code string
_LOOKUP: dict[str, BandInfo] = {}
for _b in WSPR_BANDS:
    _LOOKUP[_b.display.lower()] = _b
    _LOOKUP[str(_b.band)] = _b
    for _a in _b.aliases:
        _LOOKUP[_a.lower()] = _b

# Backward-compatible mapping from label/alias to wspr.live code
BAND_TO_WSPR_LIVE_CODE: dict[str, int] = {k: v.band for k, v in _LOOKUP.items()}

# Default rotating bands string containing all supported bands
DEFAULT_BANDS_STR: str = ",".join(b.display for b in WSPR_BANDS)


def find_band(val: int | str | None) -> Optional[BandInfo]:
    """Resolve a band identifier (int code, display name, frequency, or alias) to a BandInfo."""
    if val is None:
        return None
    if isinstance(val, int):
        return BAND_BY_CODE.get(val) or BAND_BY_FREQUENCY.get(val)
    s = str(val).strip().lower()
    if not s:
        return None
    if s in _LOOKUP:
        return _LOOKUP[s]
    # Try removing 'm' or 'cm' suffix
    if s.endswith("cm"):
        s_nocm = s[:-2]
        if s_nocm in _LOOKUP:
            return _LOOKUP[s_nocm]
    elif s.endswith("m"):
        s_nom = s[:-1]
        if s_nom in _LOOKUP:
            return _LOOKUP[s_nom]
    # Try integer code or frequency lookup
    try:
        num = int(s)
        return BAND_BY_CODE.get(num) or BAND_BY_FREQUENCY.get(num)
    except ValueError:
        pass
    return None
