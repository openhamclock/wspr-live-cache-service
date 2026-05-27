from __future__ import annotations

import asyncio
import csv
import io
import logging
import random
import time
from typing import Any

import httpx

from .config import Settings
from .db import connect, insert_spots, prune, set_state

log = logging.getLogger("wspr_live_cache.collector")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# WSPR Live stores band as the MHz-ish band bucket, not the meter label.
# Examples: 20m => band=14, 40m => band=7.
BAND_TO_WSPR_LIVE_CODE: dict[str, int] = {
    "160": 1,
    "80": 3,
    "60": 5,
    "40": 7,
    "30": 10,
    "20": 14,
    "17": 18,
    "15": 21,
    "12": 24,
    "10": 28,
    "6": 50,
    "4": 70,
    "2": 144,
}


def _configured_bands(settings: Settings) -> list[tuple[str, int]]:
    raw = getattr(settings, "bands", None) or "160,80,60,40,30,20,17,15,12,10,6,4,2"
    out: list[tuple[str, int]] = []
    for item in str(raw).split(","):
        label = item.strip().lower().removesuffix("m")
        if not label:
            continue
        code = BAND_TO_WSPR_LIVE_CODE.get(label)
        if code is None:
            log.warning("ignoring unsupported band label=%r", item)
            continue
        out.append((label, code))
    return out


def _sql_for_band(band_code: int, lookback_minutes: int, limit: int) -> str:
    lookback_minutes = max(1, int(lookback_minutes))
    limit = max(1, int(limit))
    return f"""
SELECT
    time,
    band,
    tx_sign,
    tx_loc,
    rx_sign,
    rx_loc,
    frequency,
    snr,
    power,
    drift,
    distance,
    azimuth,
    version,
    code
FROM wspr.rx
WHERE time >= now() - INTERVAL {lookback_minutes} MINUTE
  AND band = {band_code}
ORDER BY time DESC
LIMIT {limit}
FORMAT CSVWithNames
"""


def _parse_csv_with_names(text: str) -> list[dict[str, Any]]:
    if not text.strip():
        return []
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, Any]] = []
    for row in reader:
        # ClickHouse CSV can occasionally emit blank trailing rows.
        if not row or not row.get("time"):
            continue
        rows.append(row)
    return rows


def _normalize_for_db(row: dict[str, Any], band_label: str) -> dict[str, Any]:
    from datetime import datetime, timezone

    t = row.get("time")
    time_epoch = None
    if t:
        try:
            # ClickHouse usually returns UTC like: 2026-05-26 22:54:00
            dt = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            time_epoch = int(dt.timestamp())
        except Exception:
            time_epoch = None

    return {
        "time_epoch": time_epoch,
        "band": band_label,
        "tx_call": row.get("tx_sign"),
        "tx_grid": row.get("tx_loc"),
        "rx_call": row.get("rx_sign"),
        "rx_grid": row.get("rx_loc"),
        "frequency_hz": row.get("frequency"),
        "snr": row.get("snr"),
        "power_dbm": row.get("power"),
        "drift": row.get("drift"),
        "distance_km": row.get("distance"),
        "azimuth": row.get("azimuth"),
        "version": row.get("version"),
        "code": row.get("code"),
    }


async def fetch_band(
    client: httpx.AsyncClient,
    settings: Settings,
    band_label: str,
    band_code: int,
) -> list[dict[str, Any]]:
    sql = _sql_for_band(
        band_code=band_code,
        lookback_minutes=int(getattr(settings, "lookback_minutes", 10)),
        limit=int(getattr(settings, "query_limit", 100000)),
    )

    # WSPR Live currently requires GET ?query=...; POST returns 403.
    resp = await client.get(
        str(settings.wspr_live_url),
        params={"query": sql},
        timeout=float(getattr(settings, "upstream_timeout_seconds", 60)),
    )
    resp.raise_for_status()
    rows = _parse_csv_with_names(resp.text)

    # Normalize enough for DB insertion/querying.
    normalized: list[dict[str, Any]] = []
    for r in rows:
        normalized.append(
            {
                "time": r.get("time"),
                "band": int(r.get("band") or band_code),
                "band_label": band_label,
                "tx_sign": (r.get("tx_sign") or "").strip().upper(),
                "tx_loc": (r.get("tx_loc") or "").strip().upper(),
                "rx_sign": (r.get("rx_sign") or "").strip().upper(),
                "rx_loc": (r.get("rx_loc") or "").strip().upper(),
                "frequency": float(r.get("frequency") or 0),
                "snr": int(float(r.get("snr") or 0)),
                "power": int(float(r.get("power") or 0)),
                "drift": int(float(r.get("drift") or 0)),
                "distance": int(float(r.get("distance") or 0)),
                "azimuth": int(float(r.get("azimuth") or 0)),
                "version": (r.get("version") or "").strip(),
                "code": (r.get("code") or "").strip(),
            }
        )
    return normalized


async def run_collector() -> None:
    settings = Settings()
    db_conn = connect(settings.db_path)
    bands = _configured_bands(settings)

    log.info(
        "collector starting db_path=%s upstream=%s bands=%s lookback=%sm interval=%ss",
        settings.db_path,
        settings.wspr_live_url,
        ",".join(f"{label}m={code}" for label, code in bands),
        getattr(settings, "lookback_minutes", 10),
        getattr(settings, "poll_interval_seconds", 20),
    )

    if not bands:
        raise RuntimeError("no valid bands configured")

    headers = {"User-Agent": "openhamclock-wspr-live-cache/0.1"}
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        while True:
            for band_label, band_code in bands:
                started = time.monotonic()
                try:
                    rows = await fetch_band(client, settings, band_label, band_code)
                    db_rows = [_normalize_for_db(row, band_label) for row in rows]
                    inserted = insert_spots(db_conn, db_rows)
                    prune(
                        db_conn,
                        retention_hours=int(getattr(settings, "retention_hours", 48)),
                    )
                    log.info(
                        "band=%sm code=%s rows=%s inserted=%s elapsed=%.1fs",
                        band_label,
                        band_code,
                        len(rows),
                        inserted,
                        time.monotonic() - started,
                    )
                except Exception as exc:
                    log.warning(
                        "band=%sm code=%s poll failed: %r",
                        band_label,
                        band_code,
                        exc,
                    )

                interval = float(getattr(settings, "poll_interval_seconds", 20))
                jitter = float(getattr(settings, "poll_jitter_seconds", 0))
                sleep_for = interval + (random.uniform(0, jitter) if jitter > 0 else 0)
                await asyncio.sleep(sleep_for)


def main() -> None:
    asyncio.run(run_collector())


if __name__ == "__main__":
    main()
