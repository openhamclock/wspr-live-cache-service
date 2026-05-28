from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

SCHEMA = r'''
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA temp_store=MEMORY;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS spots (
    time_epoch      INTEGER NOT NULL,
    band            TEXT NOT NULL,
    tx_call         TEXT NOT NULL,
    tx_grid         TEXT,
    rx_call         TEXT NOT NULL,
    rx_grid         TEXT,
    frequency_hz    INTEGER,
    snr             INTEGER,
    power_dbm       INTEGER,
    drift           INTEGER,
    distance_km     INTEGER,
    azimuth         INTEGER,
    version         TEXT,
    code            INTEGER,
    inserted_epoch  INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    PRIMARY KEY (time_epoch, band, tx_call, rx_call, frequency_hz)
);

CREATE INDEX IF NOT EXISTS idx_spots_time ON spots(time_epoch DESC);
CREATE INDEX IF NOT EXISTS idx_spots_band_time ON spots(band, time_epoch DESC);
CREATE INDEX IF NOT EXISTS idx_spots_tx_call_time ON spots(tx_call, time_epoch DESC);
CREATE INDEX IF NOT EXISTS idx_spots_rx_call_time ON spots(rx_call, time_epoch DESC);
CREATE INDEX IF NOT EXISTS idx_spots_tx_grid4_time ON spots(substr(tx_grid,1,4), time_epoch DESC);
CREATE INDEX IF NOT EXISTS idx_spots_rx_grid4_time ON spots(substr(rx_grid,1,4), time_epoch DESC);

CREATE TABLE IF NOT EXISTS collector_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_epoch INTEGER NOT NULL
);
'''


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


_local = threading.local()


def init_schema(db_path: Path) -> None:
    """Create the schema once at startup (idempotent)."""
    connect(db_path).close()


def reader(db_path: Path) -> sqlite3.Connection:
    """Return a per-thread read-only connection.

    A single sqlite3.Connection is NOT safe to share across threads
    (check_same_thread=False only silences the guard); concurrent use
    corrupts cursor state. Each thread gets its own connection instead.
    WAL lets any number of these read concurrently with the collector's
    writes. Connections are cached per thread and reused across requests.
    """
    conn = getattr(_local, 'conn', None)
    if conn is None:
        conn = sqlite3.connect(str(db_path), timeout=30, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA busy_timeout=5000')
        conn.execute('PRAGMA temp_store=MEMORY')
        conn.execute('PRAGMA query_only=ON')
        _local.conn = conn
    return conn


def insert_spots(conn: sqlite3.Connection, spots: Iterable[dict[str, Any]]) -> int:
    rows = []
    now = int(time.time())
    for s in spots:
        if not s.get('time_epoch') or not s.get('tx_call') or not s.get('rx_call'):
            continue
        rows.append((
            int(s['time_epoch']), str(s.get('band') or '').upper().rstrip('M'),
            str(s['tx_call']).upper(), _grid(s.get('tx_grid')),
            str(s['rx_call']).upper(), _grid(s.get('rx_grid')),
            _int_or_none(s.get('frequency_hz')), _int_or_none(s.get('snr')),
            _int_or_none(s.get('power_dbm')), _int_or_none(s.get('drift')),
            _int_or_none(s.get('distance_km')), _int_or_none(s.get('azimuth')),
            s.get('version'), _int_or_none(s.get('code')), now,
        ))
    if not rows:
        return 0
    before = conn.total_changes
    conn.executemany('''
        INSERT OR IGNORE INTO spots
        (time_epoch, band, tx_call, tx_grid, rx_call, rx_grid, frequency_hz, snr, power_dbm,
         drift, distance_km, azimuth, version, code, inserted_epoch)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', rows)
    return conn.total_changes - before


def prune(conn: sqlite3.Connection, retention_hours: int) -> int:
    cutoff = int(time.time()) - retention_hours * 3600
    before = conn.total_changes
    conn.execute('DELETE FROM spots WHERE time_epoch < ?', (cutoff,))
    return conn.total_changes - before


def set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute('''
        INSERT INTO collector_state(key,value,updated_epoch) VALUES(?,?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_epoch=excluded.updated_epoch
    ''', (key, value, int(time.time())))


def get_state(conn: sqlite3.Connection) -> dict[str, str]:
    return {r['key']: r['value'] for r in conn.execute('SELECT key,value FROM collector_state')}


def query_spots(
    conn: sqlite3.Connection,
    *,
    ofcall: str | None = None,
    bycall: str | None = None,
    ofgrid: str | None = None,
    bygrid: str | None = None,
    band: str | None = None,
    maxage: int = 900,
    limit: int = 5000,
) -> list[sqlite3.Row]:
    cutoff = int(time.time()) - maxage
    where = ['time_epoch >= ?']
    args: list[Any] = [cutoff]
    if ofcall:
        where.append('tx_call = ?')
        args.append(ofcall.upper())
    if bycall:
        where.append('rx_call = ?')
        args.append(bycall.upper())
    if ofgrid:
        where.append('substr(tx_grid,1,4) = ?')
        args.append(ofgrid[:4].upper())
    if bygrid:
        where.append('substr(rx_grid,1,4) = ?')
        args.append(bygrid[:4].upper())
    if band:
        where.append('band = ?')
        args.append(band.upper().rstrip('M'))
    args.append(limit)
    return list(conn.execute(f'''
        SELECT time_epoch, band, tx_call, tx_grid, rx_call, rx_grid, frequency_hz, snr,
               power_dbm, drift, distance_km, azimuth, version, code
        FROM spots
        WHERE {' AND '.join(where)}
        ORDER BY time_epoch DESC
        LIMIT ?
    ''', args))


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute('SELECT COUNT(*) c, MIN(time_epoch) oldest, MAX(time_epoch) newest FROM spots').fetchone()
    bands = {r['band']: r['c'] for r in conn.execute('SELECT band, COUNT(*) c FROM spots GROUP BY band ORDER BY band')}
    return {'count': row['c'], 'oldest_epoch': row['oldest'], 'newest_epoch': row['newest'], 'bands': bands, 'state': get_state(conn)}


def _grid(v: Any) -> str | None:
    if not v:
        return None
    g = str(v).strip().upper()
    return g or None


def _int_or_none(v: Any) -> int | None:
    if v is None or v == '':
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None
