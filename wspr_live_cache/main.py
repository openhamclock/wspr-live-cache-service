from __future__ import annotations

import time
from typing import Optional

from fastapi import FastAPI, Query, Response
from fastapi.responses import PlainTextResponse

from .config import settings
from .db import connect, query_spots, stats

app = FastAPI(title='Open HamClock WSPR Live Cache', version='1.0.0')
_conn = connect(settings.db_path)
_response_cache: dict[str, tuple[float, str, str]] = {}


def clamp_maxage(maxage: Optional[int]) -> int:
    if maxage is None or maxage <= 0:
        return settings.default_query_age_seconds
    return min(maxage, settings.max_query_age_seconds)


def cache_key(params: dict[str, object], fmt: str) -> str:
    return fmt + ':' + '&'.join(f'{k}={v}' for k, v in sorted(params.items()) if v not in (None, ''))


def get_cached(key: str) -> Optional[tuple[str, str]]:
    item = _response_cache.get(key)
    if not item:
        return None
    expires, body, media_type = item
    if time.time() > expires:
        _response_cache.pop(key, None)
        return None
    return body, media_type


def put_cached(key: str, body: str, media_type: str) -> None:
    _response_cache[key] = (time.time() + settings.response_cache_seconds, body, media_type)


@app.get('/healthz')
def healthz():
    s = stats(_conn)
    newest = s.get('newest_epoch')
    age = int(time.time()) - newest if newest else None
    return {'ok': True, 'upstream_queries_from_api': False, 'spot_count': s['count'], 'newest_age_seconds': age}


@app.get('/stats')
def get_stats():
    s = stats(_conn)
    s['upstream_queries_from_api'] = False
    s['max_query_age_seconds'] = settings.max_query_age_seconds
    s['retention_hours'] = settings.retention_hours
    return s


@app.get('/api/wspr/spots')
def api_spots(
    ofcall: Optional[str] = None,
    bycall: Optional[str] = None,
    ofgrid: Optional[str] = None,
    bygrid: Optional[str] = None,
    band: Optional[str] = None,
    maxage: Optional[int] = Query(default=None),
    limit: int = Query(default=5000, le=50000),
):
    age = clamp_maxage(maxage)
    rows = query_spots(_conn, ofcall=ofcall, bycall=bycall, ofgrid=ofgrid, bygrid=bygrid, band=band, maxage=age, limit=limit)
    return {'source': 'local-cache-only', 'maxage': age, 'count': len(rows), 'spots': [dict(r) for r in rows]}


@app.get('/ham/HamClock/fetchWSPR.pl', response_class=PlainTextResponse)
def hamclock_fetch(
    ofcall: Optional[str] = None,
    bycall: Optional[str] = None,
    ofgrid: Optional[str] = None,
    bygrid: Optional[str] = None,
    band: Optional[str] = None,
    maxage: Optional[int] = Query(default=None),
):
    age = clamp_maxage(maxage)
    params = {'ofcall': ofcall, 'bycall': bycall, 'ofgrid': ofgrid, 'bygrid': bygrid, 'band': band, 'maxage': age}
    key = cache_key(params, 'hamclock')
    cached = get_cached(key)
    if cached:
        body, media_type = cached
        return Response(content=body, media_type=media_type, headers={'X-WSPR-Cache': 'HIT', 'X-Upstream-Queries': '0'})
    rows = query_spots(_conn, ofcall=ofcall, bycall=bycall, ofgrid=ofgrid, bygrid=bygrid, band=band, maxage=age, limit=5000)
    body = render_hamclock(rows)
    put_cached(key, body, 'text/plain')
    return Response(content=body, media_type='text/plain', headers={'X-WSPR-Cache': 'MISS', 'X-Upstream-Queries': '0'})


def render_hamclock(rows) -> str:
    # CSV-ish format kept intentionally simple for shim compatibility.
    # Fields: epoch,tx_call,tx_grid,rx_call,rx_grid,freq_hz,snr,band,power,drift,distance,azimuth
    lines = ['# epoch,tx_call,tx_grid,rx_call,rx_grid,freq_hz,snr,band,power,drift,distance,azimuth']
    for r in rows:
        lines.append(','.join(_csv(v) for v in [
            r['time_epoch'], r['tx_call'], r['tx_grid'], r['rx_call'], r['rx_grid'],
            r['frequency_hz'], r['snr'], r['band'], r['power_dbm'], r['drift'], r['distance_km'], r['azimuth']
        ]))
    return '\n'.join(lines) + '\n'


def _csv(v) -> str:
    if v is None:
        return ''
    s = str(v)
    if ',' in s or '"' in s:
        s = '"' + s.replace('"', '""') + '"'
    return s
