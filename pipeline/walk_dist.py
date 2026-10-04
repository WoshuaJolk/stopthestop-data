"""Street walking distance from each stop to its adjacent stops, via Valhalla. Writes results/walk_street.csv."""
import csv
import os
import time

import requests

from analyze import build_graph, load_patterns, load_stations
from paths import GTFS, RESULTS, STATIONS

URL = "https://valhalla1.openstreetmap.de/sources_to_targets"
OUT = RESULTS / "walk_street.csv"


def main():
    stations = load_stations(STATIONS)
    _, _, _, neighbors, _ = build_graph(load_patterns(GTFS), stations)
    done = set()
    if os.path.exists(OUT):
        with open(OUT) as f:
            done = {r["from"] for r in csv.DictReader(f)}
    new = not os.path.exists(OUT)
    with open(OUT, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["from", "to", "meters"])
        for stop in sorted(neighbors):
            nbrs = sorted(n for n in neighbors[stop] if n in stations)
            if stop not in stations or stop in done or not nbrs:
                continue
            loc = lambda s: {"lat": stations[s]["ll"][0], "lon": stations[s]["ll"][1]}
            body = {"sources": [loc(stop)], "targets": [loc(n) for n in nbrs], "costing": "pedestrian", "units": "kilometers"}
            for attempt in range(5):
                try:
                    r = requests.post(URL, json=body, timeout=60)
                    r.raise_for_status()
                    break
                except requests.RequestException as e:
                    print(f"{stop} attempt {attempt}: {e}", flush=True)
                    time.sleep(5 * (attempt + 1))
            else:
                raise SystemExit(f"{stop} failed")
            for n, cell in zip(nbrs, r.json()["sources_to_targets"][0]):
                w.writerow([stop, n, round(cell["distance"] * 1000) if cell["distance"] is not None else ""])
            f.flush()
            time.sleep(1.1)  # public server asks for <= 1 req/s


if __name__ == "__main__":
    main()
