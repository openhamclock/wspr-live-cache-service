# Copyright (C) 2026 Open HamClock Backend (OHB) Contributors
# License: GNU Affero General Public License v3.0 (AGPLv3)
# See LICENSE file or <https://www.gnu.org/licenses/agpl-3.0.html>
#

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


def _csv(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default).strip()
    return [x.strip() for x in raw.split(',') if x.strip()]


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    db_path: Path = Path(os.getenv('WSPR_DB_PATH', '/data/wspr-live-cache.sqlite3'))
    wspr_live_url: str = os.getenv('WSPR_LIVE_URL', 'https://db1.wspr.live/').rstrip('/') + '/'
    bands: str = os.getenv('WSPR_BANDS', "160,80,60,40,30,20,17,15,12,10,6,4,2")
    poll_lookback_minutes: int = _int('WSPR_POLL_LOOKBACK_MINUTES', 10)
    poll_interval_seconds: float = _float('WSPR_POLL_INTERVAL_SECONDS', 20.0)
    poll_jitter_seconds: float = _float('WSPR_POLL_JITTER_SECONDS', 0.0)
    cycle_sleep_seconds: float = _float('WSPR_CYCLE_SLEEP_SECONDS', 10.0)
    upstream_timeout_seconds: float = _float('WSPR_UPSTREAM_TIMEOUT_SECONDS', 25.0)
    retention_hours: float = _float('WSPR_RETENTION_HOURS', 24)
    prune_every_seconds: int = _int('WSPR_PRUNE_EVERY_SECONDS', 900)
    max_rows_per_band_poll: int = _int('WSPR_MAX_ROWS_PER_BAND_POLL', 100000)
    max_query_age_seconds: int = _int('WSPR_MAX_QUERY_AGE_SECONDS', 86400)
    default_query_age_seconds: int = _int('WSPR_DEFAULT_QUERY_AGE_SECONDS', 900)
    response_cache_seconds: int = _int('WSPR_RESPONSE_CACHE_SECONDS', 45)
    stats_cache_seconds: float = _float('WSPR_STATS_CACHE_SECONDS', 5.0)
    workers: int = _int('WSPR_WORKERS', 4)
    # important safety switch: API never queries upstream. Only collector does.
    api_upstream_disabled: bool = os.getenv('WSPR_API_UPSTREAM_DISABLED', 'true').lower() not in ('0','false','no')


settings = Settings()
