#!/usr/bin/env python3
"""Load generator for the WSPR live cache, modeling many HamClock clients.

Two modes:
  realistic : N virtual clients, each with its OWN fixed grid, each polling
              every --interval seconds (with jitter). Models steady state.
  stress    : --clients threads hammering with no sleep and a fresh random
              grid every request (defeats the cache) to find the ceiling.

Stdlib only. Examples:
  python3 loadtest.py --stress --clients 200 --duration 30
  python3 loadtest.py --clients 1000 --interval 90 --duration 60
"""
import argparse, random, statistics, threading, time, urllib.request, urllib.error
from collections import Counter

def rand_grid():
    # 6-char Maidenhead-ish; only the first 4 chars affect the query/cache key.
    return (random.choice("CDEFGHIJ") + random.choice("KLMNOPQR")
            + str(random.randint(0, 9)) + str(random.randint(0, 9))
            + random.choice("ABVTXIWN") + random.choice("JKTILR"))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8081/ham/HamClock/fetchWSPR.pl")
    ap.add_argument("--clients", type=int, default=200, help="concurrent virtual clients / threads")
    ap.add_argument("--interval", type=float, default=90.0, help="realistic mode: seconds between a client's polls")
    ap.add_argument("--duration", type=float, default=30.0, help="test length in seconds")
    ap.add_argument("--maxage", type=int, default=900)
    ap.add_argument("--stress", action="store_true", help="max-throughput mode (no sleep, fresh grid each request)")
    ap.add_argument("--timeout", type=float, default=10.0)
    args = ap.parse_args()

    stop = time.time() + args.duration
    lats, codes, caches = [], Counter(), Counter()
    errors = 0
    lock = threading.Lock()

    def do_request(grid):
        nonlocal errors
        url = f"{args.url}?ofgrid={grid}&maxage={args.maxage}"
        t0 = time.perf_counter()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "loadtest"})
            with urllib.request.urlopen(req, timeout=args.timeout) as resp:
                resp.read()
                dt = (time.perf_counter() - t0) * 1000
                with lock:
                    lats.append(dt); codes[resp.status] += 1
                    caches[resp.headers.get("X-WSPR-Cache", "?")] += 1
        except urllib.error.HTTPError as e:
            with lock:
                codes[e.code] += 1; errors += 1
        except Exception as e:
            with lock:
                codes[type(e).__name__] += 1; errors += 1

    def worker(home_grid):
        # stagger startup so clients don't all fire in lockstep
        time.sleep(random.uniform(0, min(args.interval, 2.0)))
        while time.time() < stop:
            do_request(rand_grid() if args.stress else home_grid)
            if not args.stress:
                time.sleep(args.interval * random.uniform(0.5, 1.5))

    grids = [rand_grid() for _ in range(args.clients)]
    threads = [threading.Thread(target=worker, args=(g,), daemon=True) for g in grids]
    print(f"mode={'stress' if args.stress else 'realistic'} clients={args.clients} "
          f"duration={args.duration}s url={args.url}")
    t_start = time.perf_counter()
    for t in threads: t.start()
    for t in threads: t.join(timeout=args.duration + args.timeout + 5)
    wall = time.perf_counter() - t_start

    total = sum(codes.values())
    print(f"\nrequests={total}  errors={errors}  wall={wall:.1f}s  throughput={total/wall:.1f} req/s")
    print(f"status/result codes: {dict(codes)}")
    print(f"cache: {dict(caches)}")
    if lats:
        lats.sort()
        pct = lambda p: lats[min(len(lats) - 1, int(p * len(lats)))]
        print(f"latency ms: p50={statistics.median(lats):.1f}  p90={pct(.90):.1f}  "
              f"p95={pct(.95):.1f}  p99={pct(.99):.1f}  max={lats[-1]:.1f}")
    print("\nRESULT:", "PASS (0 errors)" if errors == 0 else f"FAIL ({errors} errors)")

if __name__ == "__main__":
    main()
