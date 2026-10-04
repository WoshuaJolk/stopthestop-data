"""Street walk from each entrance of a stop to the nearest entrance of an adjacent station, via Valhalla.
Writes results/walk_entrance.csv (one row per source entrance)."""
import csv
import os
import time

import pandas as pd
import requests

from analyze import build_graph, load_patterns, load_stations
from paths import ENTRANCES, GTFS, RESULTS, STATIONS

URL = "https://valhalla1.openstreetmap.de/sources_to_targets"
OUT = RESULTS / "walk_entrance.csv"
MAX_CELLS = 100  # server limit on sources x targets
DEDUPE = 4  # decimal places (~10 m); paired stairs collapse to one point


def load_entrances(stations):
    e = pd.read_csv(ENTRANCES, dtype=str)
    e = e[(e["Entry Allowed"] == "YES") | (e["Exit Allowed"] == "YES")]
    # the file's own Complex ID is wrong for a few stations; derive it from the GTFS stop ID
    e["stop"] = e["GTFS Stop ID"].str.split(";").str[0].str.strip()
    e["complex"] = e["stop"].map(lambda x: stations[x]["complex"] if x in stations else None)
    e = e.dropna(subset=["complex"])
    pts = lambda g: sorted({(round(float(a), DEDUPE), round(float(b), DEDUPE))
                            for a, b in zip(g["Entrance Latitude"], g["Entrance Longitude"])})
    by_stop = {s: pts(g) for s, g in e.groupby("stop")}
    by_complex = {c: pts(g) for c, g in e.groupby("complex")}
    return by_stop, by_complex


def post(stop, body):
    for attempt in range(5):
        try:
            r = requests.post(URL, json=body, timeout=60)
            r.raise_for_status()
            return r.json()["sources_to_targets"]
        except requests.RequestException as e:
            print(f"{stop} attempt {attempt}: {e}", flush=True)
            time.sleep(5 * (attempt + 1))
    raise SystemExit(f"{stop} failed")


def main():
    stations = load_stations(STATIONS)
    _, _, _, neighbors, _ = build_graph(load_patterns(GTFS), stations)
    by_stop, by_complex = load_entrances(stations)
    done = set()
    if os.path.exists(OUT):
        with open(OUT) as f:
            done = {r["stop"] for r in csv.DictReader(f)}
    new = not os.path.exists(OUT)
    with open(OUT, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["stop", "lat", "lon", "to_stop", "meters"])
        for stop in sorted(neighbors):
            if stop not in stations or stop in done:
                continue
            src = by_stop.get(stop) or by_complex.get(stations[stop]["complex"]) or [stations[stop]["ll"]]
            tgt = []
            for n in sorted(neighbors[stop]):
                if n in stations:
                    pts = by_complex.get(stations[n]["complex"]) or [stations[n]["ll"]]
                    tgt += [(n, p) for p in pts]
            rows = [[] for _ in src]
            step = max(1, MAX_CELLS // len(src))
            for k in range(0, len(tgt), step):
                body = {"sources": [{"lat": a, "lon": b} for a, b in src],
                        "targets": [{"lat": a, "lon": b} for _, (a, b) in tgt[k:k + step]],
                        "costing": "pedestrian", "units": "kilometers"}
                rows = [acc + part for acc, part in zip(rows, post(stop, body))]
                time.sleep(1.1)
            for (lat, lon), row in zip(src, rows):
                best = min(((c["distance"], tgt[j][0]) for j, c in enumerate(row) if c["distance"] is not None), default=None)
                w.writerow([stop, lat, lon, best[1] if best else "", round(best[0] * 1000) if best else ""])
            f.flush()


if __name__ == "__main__":
    main()
