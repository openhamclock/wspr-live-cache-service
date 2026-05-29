# Open HamClock WSPR Live Cache Service

This container makes WSPR Live safe for a large Open HamClock Backend deployment by putting a hard cache boundary between HamClock traffic and upstream `wspr.live`.

HamClock never reaches WSPR Live directly:

```text
HamClock -> OHB fetchWSPR.pl shim -> wspr-cache-api -> SQLite
                                      ^
                                      |
                         wspr-cache-collector -> wspr.live
```

The API container never performs upstream queries. Only the collector talks to WSPR Live on a controlled schedule.

## What it does

- Polls `wspr.live` ClickHouse by band in the background.
- Pulls only a recent overlapping lookback window, default 10 minutes.
- Deduplicates into SQLite using WAL mode.
- Retains local spots for 48 hours by default.
- Allows HamClock-style queries up to 24 hours from local cache only.
- Supports `ofcall`, `bycall`, `ofgrid`, `bygrid`, `band`, and `maxage`.
- Includes a drop-in `fetchWSPR.pl` shim for OHB/lighttpd.

## Run

```bash
cd docker
./build-image.sh
docker compose up -d
curl http://localhost:8081/healthz
curl 'http://localhost:8081/stats'
curl 'http://localhost:8081/ham/HamClock/fetchWSPR.pl?ofgrid=EL98&maxage=900'
```

## OHB shim

Install `fetchWSPR.pl` as the HamClock-facing CGI in OHB and set:

```bash
WSPR_CACHE_URL=http://wspr-cache-api:8081/ham/HamClock/fetchWSPR.pl
```

If OHB is not in the same Docker network, expose the cache API on the host and use:

```bash
WSPR_CACHE_URL=http://127.0.0.1:8081/ham/HamClock/fetchWSPR.pl
```

The shim deliberately has **no fallback** to WSPR Live. If the cache is down, it returns an empty/comment response instead of hammering upstream.

## Configuration

| Variable | Default | Meaning |
|---|---:|---|
| `WSPR_LIVE_URL` | `https://db1.wspr.live/` | ClickHouse HTTP endpoint |
| `WSPR_BANDS` | `160,80,60,40,30,20,17,15,12,10,6,4,2` | Rotating band list |
| `WSPR_POLL_LOOKBACK_MINUTES` | `10` | Overlap window per band poll |
| `WSPR_POLL_INTERVAL_SECONDS` | `20` | Delay between band polls |
| `WSPR_CYCLE_SLEEP_SECONDS` | `10` | Delay after a full band cycle |
| `WSPR_RETENTION_HOURS` | `48` | Local raw spot retention |
| `WSPR_MAX_QUERY_AGE_SECONDS` | `86400` | HamClock max query age cap |
| `WSPR_RESPONSE_CACHE_SECONDS` | `45` | Short API response cache |
| `WSPR_MAX_ROWS_PER_BAND_POLL` | `100000` | Safety cap per upstream query |

## Notes

The collector queries one band at a time using SQL like:

```sql
SELECT time, band, tx_sign, tx_loc, rx_sign, rx_loc, frequency, snr, power,
       drift, distance, azimuth, version, code
FROM wspr.rx
WHERE time >= now() - INTERVAL 10 MINUTE
  AND band = '20'
ORDER BY time DESC
LIMIT 100000
FORMAT CSVWithNames
```

The API answers from SQLite only. Headers include `X-Upstream-Queries: 0` to make that behavior explicit.
