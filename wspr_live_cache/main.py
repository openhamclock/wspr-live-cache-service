from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Optional, Any

from fastapi import FastAPI, Query, Response
from fastapi.responses import PlainTextResponse

from .collector import run_collector
from .config import settings
from .db import connect, query_spots, stats

_conn = connect(settings.db_path)
_response_cache: dict[str, tuple[float, str, str]] = {}
_RESPONSE_CACHE_MAX_ENTRIES = 2000

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the background collector task, sharing our DB connection
    collector_task = asyncio.create_task(run_collector(_conn))
    yield
    # Clean up the task on shutdown gracefully
    collector_task.cancel()
    try:
        await collector_task
    except asyncio.CancelledError:
        pass
    title='Open HamClock WSPR Live Cache',
    version='1.0.0',
    lifespan=lifespan

app = FastAPI(
    title='Open HamClock WSPR Live Cache',
    version='1.0.0',
    lifespan=lifespan
)


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
    now = time.time()
    # Drop expired entries so keys for one-off queries don't accumulate forever.
    expired = [k for k, (exp, _, _) in _response_cache.items() if exp <= now]
    for k in expired:
        _response_cache.pop(k, None)
    # Hard cap as a backstop: evict the soonest-to-expire entries if still oversized.
    if len(_response_cache) >= _RESPONSE_CACHE_MAX_ENTRIES:
        for k in sorted(_response_cache, key=lambda k: _response_cache[k][0])[
            : len(_response_cache) - _RESPONSE_CACHE_MAX_ENTRIES + 1
        ]:
            _response_cache.pop(k, None)
    _response_cache[key] = (now + settings.response_cache_seconds, body, media_type)


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
    # HamClock (pskreporter.cpp) parses every line with a single sscanf:
    #   "%ld,%6[^,],%63[^,],%6[^,],%63[^,],%7[^,],%ld,%f"
    # i.e. EXACTLY these 8 fields, in this order:
    #   epoch, tx_grid, tx_call, rx_grid, rx_call, mode, freq_hz, snr
    # Any line that doesn't yield all 8 fields makes HamClock abort the ENTIRE
    # response (it does `goto out`, not skip-this-line), so we must be strict:
    #   - no header/comment line (it would fail parsing and zero everything out)
    #   - never emit an empty grid (an empty field can't match %6[^,])
    #   - cap grids at 6 chars (a longer grid desyncs the comma alignment)
    #   - mode must be a non-empty token; "WSPR" is the correct value here
    lines = []
    for r in rows:
        tx_grid = (r['tx_grid'] or '')[:6]
        rx_grid = (r['rx_grid'] or '')[:6]
        if not tx_grid or not rx_grid:
            continue
        lines.append(','.join(_csv(v) for v in [
            r['time_epoch'], tx_grid, r['tx_call'], rx_grid, r['rx_call'],
            'WSPR', r['frequency_hz'], r['snr'],
        ]))
    return '\n'.join(lines) + '\n' if lines else ''


def _csv(v) -> str:
    if v is None:
        return ''
    s = str(v)
    if ',' in s or '"' in s:
        s = '"' + s.replace('"', '""') + '"'
    return s
