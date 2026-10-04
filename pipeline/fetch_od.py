"""Pull OD ridership for one year/month in per-hour chunks, saved to data/od/ (or data/od_wkday/ with --weekday)."""
import csv
import os
import sys
import time

import requests

from paths import OD, OD_WEEKDAY

URL = "https://data.ny.gov/resource/28vm-gjqr.json"
LIMIT = 50000


WEEKDAYS = "day_of_week in ('Monday','Tuesday','Wednesday','Thursday','Friday')"


def fetch_hour(year, month, hour, out, weekday=False):
    rows, offset = [], 0
    headers = {"X-App-Token": os.environ["SOCRATA_APP_TOKEN"]} if os.environ.get("SOCRATA_APP_TOKEN") else {}
    while True:
        params = {
            "$select": "origin_station_complex_id,destination_station_complex_id,sum(estimated_average_ridership) as riders",
            "$where": f"year={year} AND month={month} AND hour_of_day={hour}" + (f" AND {WEEKDAYS}" if weekday else ""),
            "$group": "origin_station_complex_id,destination_station_complex_id",
            "$order": "origin_station_complex_id,destination_station_complex_id",
            "$limit": LIMIT,
            "$offset": offset,
        }
        for attempt in range(5):
            try:
                r = requests.get(URL, params=params, headers=headers, timeout=300)
                r.raise_for_status()
                break
            except requests.RequestException as e:
                print(f"  hour {hour} offset {offset} attempt {attempt}: {e}", flush=True)
                time.sleep(10 * (attempt + 1))
        else:
            raise SystemExit(f"hour {hour} failed")
        page = r.json()
        rows += page
        if len(page) < LIMIT:
            break
        offset += LIMIT
    tmp = out + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["origin", "destination", "riders"])
        for p in rows:
            w.writerow([p["origin_station_complex_id"], p["destination_station_complex_id"], p["riders"]])
    os.replace(tmp, out)
    return len(rows)


if __name__ == "__main__":
    # --weekday: sum over Monday-Friday only
    weekday = "--weekday" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    year, month = (int(a) for a in args[:2]) if len(args) > 1 else (2026, 5)
    folder = OD_WEEKDAY if weekday else OD
    os.makedirs(folder, exist_ok=True)
    for hour in range(24):
        out = f"{folder}/{year}-{month:02d}-h{hour:02d}.csv"
        if os.path.exists(out):
            continue
        t = time.time()
        n = fetch_hour(year, month, hour, out, weekday)
        print(f"hour {hour}: {n} pairs in {time.time() - t:.0f}s", flush=True)
