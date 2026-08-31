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
curl http://localhost:5001/healthz
curl 'http://localhost:5001/stats'
curl 'http://localhost:5001/ham/HamClock/fetchWSPR.pl?ofgrid=EL98&maxage=900'
```

## OHB shim

Install `fetchWSPR.pl` as the HamClock-facing CGI in OHB and set:

```bash
WSPR_CACHE_URL=http://wspr-cache-api:5001/ham/HamClock/fetchWSPR.pl
```

If OHB is not in the same Docker network, expose the cache API on the host and use:

```bash
WSPR_CACHE_URL=http://127.0.0.1:5001/ham/HamClock/fetchWSPR.pl
```

The shim deliberately has **no fallback** to WSPR Live. If the cache is down, it returns an empty/comment response instead of hammering upstream.

## Configuration

| Variable | Default | Meaning |
|---|---:|---|
| `WSPR_LIVE_URL` | `https://db1.wspr.live/` | ClickHouse HTTP endpoint |
| `WSPR_BANDS` | `LF,MF,160m,80m,60m,40m,30m,20m,17m,15m,12m,10m,6m,4m,2m,70cm,23cm` | Rotating band list (all supported bands) |
| `WSPR_POLL_LOOKBACK_MINUTES` | `10` | Overlap window per band poll |
| `WSPR_POLL_INTERVAL_SECONDS` | `20` | Delay between band polls |
| `WSPR_CYCLE_SLEEP_SECONDS` | `10` | Delay after a full band cycle |
| `WSPR_RETENTION_HOURS` | `48` | Local raw spot retention |
| `WSPR_MAX_QUERY_AGE_SECONDS` | `86400` | HamClock max query age cap |
| `WSPR_RESPONSE_CACHE_SECONDS` | `45` | Short API response cache |
| `WSPR_MAX_ROWS_PER_BAND_POLL` | `100000` | Safety cap per upstream query |

## Supported Bands and Frequencies

The service supports all 17 WSPR bands:

| Band | Frequency (Hz) | Display |
|---:|---:|---|
| -1 | 136000 | LF |
| 0 | 474200 | MF |
| 1 | 1836600 | 160m |
| 3 | 3568600 | 80m |
| 5 | 5287200 | 60m |
| 7 | 7038600 | 40m |
| 10 | 10138700 | 30m |
| 14 | 14095600 | 20m |
| 18 | 18104600 | 17m |
| 21 | 21094600 | 15m |
| 24 | 24924600 | 12m |
| 28 | 28124600 | 10m |
| 50 | 50293000 | 6m |
| 70 | 70091000 | 4m |
| 144 | 144489000 | 2m |
| 432 | 432300000 | 70cm |
| 1296 | 1296500000 | 23cm |

A JSON list of all supported bands is also available at `/api/wspr/bands`.

## Notes

The collector queries one band at a time using SQL like:

```sql
SELECT time, band, tx_sign, tx_loc, rx_sign, rx_loc, frequency, snr, power,
       drift, distance, azimuth, version, code
FROM wspr.rx
WHERE time >= now() - INTERVAL 10 MINUTE
  AND band = 14
ORDER BY time DESC
LIMIT 100000
FORMAT CSVWithNames
```

The API answers from SQLite only. Headers include `X-Upstream-Queries: 0` to make that behavior explicit.

## Releases & Docker Builds

For instructions on building local images, setting up SSH signing keys, and triggering releases via GitHub Actions, see [RELEASE.md](RELEASE.md).

## License

Copyright (C) 2026 Open HamClock Backend (OHB) Contributors.
This project is licensed under the GNU Affero General Public License v3.0 (AGPLv3).
See the LICENSE file or <https://www.gnu.org/licenses/agpl-3.0.html> for details.
