"""3 Av's walkshed: every street point closer to 3 Av than to any other station, weighted by residents and jobs,
with its extra walk to the next L station. Writes results/third_ave/walkshed.json (Exhibit F)."""
import json

import numpy as np
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

import catchment as C
from analyze import load_stations
from paths import RESULTS, STATIONS
from walk_entrances import load_entrances

STOP = "L05"
C.BBOX = (-74.015, 40.715, -73.955, 40.750)  # lower Manhattan window, enough to contain the walkshed


def main():
    stations = load_stations(STATIONS)
    by_stop, by_complex = load_entrances(stations)
    g, p = C.load_network()
    tree = cKDTree(p)
    pop, jobs = C.load_weights(tree)
    inb = lambda ll: C.BBOX[0] <= ll[1] <= C.BBOX[2] and C.BBOX[1] <= ll[0] <= C.BBOX[3]
    stops = sorted(s for s in stations if inb(stations[s]["ll"]))
    cx = np.array([stations[s]["complex"] for s in stops])
    routes = [set(stations[s]["routes"].split()) for s in stops]
    q = lambda pts: np.unique(tree.query(C.xy([v[1] for v in pts], [v[0] for v in pts]))[1])
    sources = []
    for s in stops:
        own = by_stop.get(s) or by_complex.get(stations[s]["complex"]) or [stations[s]["ll"]]
        anyc = by_complex.get(stations[s]["complex"]) or own
        sources.append((q(own), q(anyc)))
    best, owner = np.full(len(p), np.inf), np.full(len(p), -1)
    for k, (own, _) in enumerate(sources):
        d = dijkstra(g, indices=own, min_only=True, limit=C.CATCHMENT)
        closer = d < best
        best[closer], owner[closer] = d[closer], k
    k3 = stops.index(STOP)
    catch = np.flatnonzero(owner == k3)
    alt, via = np.full(len(catch), C.LIMIT), np.full(len(catch), -1)
    for k, (_, anyc) in enumerate(sources):
        if cx[k] == cx[k3] or not (routes[k] & routes[k3]):
            continue
        d = dijkstra(g, indices=anyc, min_only=True, limit=C.LIMIT)[catch]
        better = d < alt
        alt[better], via[better] = d[better], k
    w = pop[catch] + jobs[catch]
    extra = alt - best[catch]
    print(f"points {len(catch)}, weighted extra walk {(w * extra).sum() / w.sum():.0f} m, "
          f"residents {pop[catch].sum():,.0f}, jobs {jobs[catch].sum():,.0f}")
    k = 111320.0 * np.cos(np.radians(C.LAT0))
    lon, lat = p[catch, 0] / k, p[catch, 1] / 110540.0
    out = dict(
        columns=["lon", "lat", "residents_plus_jobs", "extra_walk_m", "walk_to_stop"],
        points=[[round(a, 5), round(b, 5), round(float(c)), round(float(e)), stops[v] if v >= 0 else None]
                for a, b, c, e, v in zip(lon, lat, w, extra, via)],
        entrances={s: by_stop.get(s) or by_complex.get(stations[s]["complex"], []) for s in ("L03", "L05", "L06")},
    )
    (RESULTS / "third_ave").mkdir(exist_ok=True)
    json.dump(out, open(RESULTS / "third_ave" / "walkshed.json", "w"))


if __name__ == "__main__":
    main()
