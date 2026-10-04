"""Population- and job-weighted added walk if a stop is cut, on the OSM street network.
Writes results/walk_catchment.csv."""
import glob
import gzip
import math

import numpy as np
import osmium
import pandas as pd
from dbfread import DBF
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from analyze import load_stations
from walk_entrances import load_entrances
from paths import BLOCKS, OSM, RESULTS, STATIONS, WAC

BBOX = (-74.06, 40.54, -73.70, 40.92)  # lon/lat, NYC minus Staten Island
LAT0 = 40.73
WALKABLE = {"footway", "path", "pedestrian", "steps", "residential", "living_street", "service", "unclassified",
            "tertiary", "secondary", "primary", "tertiary_link", "secondary_link", "primary_link", "cycleway",
            "track", "corridor", "crossing", "road", "busway"}
LIMIT = 3000.0  # m, Dijkstra radius per station
CATCHMENT = 1200.0  # m, farthest walk counted as a station's user


def xy(lon, lat):
    k = 111320.0
    return np.column_stack([np.asarray(lon) * k * math.cos(math.radians(LAT0)), np.asarray(lat) * 110540.0])


def load_network(path=OSM):
    ids, lons, lats, a, b = {}, [], [], [], []
    fp = osmium.FileProcessor(path).with_locations().with_filter(osmium.filter.KeyFilter("highway"))
    for w in fp:
        if not w.is_way():
            continue
        t = w.tags
        if t.get("highway") not in WALKABLE or t.get("foot") == "no" or t.get("access") in ("private", "no"):
            continue
        prev = None
        for n in w.nodes:
            if not n.location.valid():
                prev = None
                continue
            lon, lat = n.location.lon, n.location.lat
            if not (BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]):
                prev = None
                continue
            i = ids.get(n.ref)
            if i is None:
                i = ids[n.ref] = len(lons)
                lons.append(lon)
                lats.append(lat)
            if prev is not None:
                a.append(prev)
                b.append(i)
            prev = i
    del ids
    p = xy(lons, lats)
    a, b = np.array(a), np.array(b)
    d = np.hypot(*(p[a] - p[b]).T)
    n = len(p)
    g = coo_matrix((np.r_[d, d], (np.r_[a, b], np.r_[b, a])), shape=(n, n)).tocsr()
    return g, p


def load_weights(tree):
    blocks = []
    for f in [BLOCKS]:
        for r in DBF(f, load=False):
            blocks.append((r["GEOID20"], float(r["INTPTLON20"]), float(r["INTPTLAT20"]), r["POP20"]))
    b = pd.DataFrame(blocks, columns=["geoid", "lon", "lat", "pop"])
    with gzip.open(WAC, "rt") as f:
        wac = pd.read_csv(f, usecols=["w_geocode", "C000"], dtype={"w_geocode": str})
    b["jobs"] = b.geoid.map(dict(zip(wac.w_geocode, wac.C000))).fillna(0)
    b = b[(b.lon >= BBOX[0]) & (b.lon <= BBOX[2]) & (b.lat >= BBOX[1]) & (b.lat <= BBOX[3])]
    _, node = tree.query(xy(b.lon, b.lat))
    pop = np.bincount(node, weights=b["pop"], minlength=tree.n)
    jobs = np.bincount(node, weights=b.jobs, minlength=tree.n)
    print(f"blocks {len(b)}, residents {b['pop'].sum():,.0f}, jobs {b.jobs.sum():,.0f}")
    return pop, jobs


def main():
    stations = load_stations(STATIONS)
    by_stop, by_complex = load_entrances(stations)
    g, p = load_network()
    tree = cKDTree(p)
    print(f"walk network: {g.shape[0]:,} nodes, {g.nnz // 2:,} edges")
    pop, jobs = load_weights(tree)

    stops = sorted(stations)
    cx = np.array([stations[s]["complex"] for s in stops])
    routes = [set(stations[s]["routes"].split()) for s in stops]
    shares = np.array([[bool(a & b) for b in routes] for a in routes])
    sources = []
    for s in stops:
        # a station's own users start at its own entrances; as an alternative, any entrance of its complex counts
        own = by_stop.get(s) or by_complex.get(stations[s]["complex"]) or [stations[s]["ll"]]
        anyc = by_complex.get(stations[s]["complex"]) or own
        q = lambda pts: np.unique(tree.query(xy([v[1] for v in pts], [v[0] for v in pts]))[1])
        sources.append((q(own), q(anyc)))

    best, owner = np.full(len(p), np.inf), np.full(len(p), -1)
    for k, (own, _) in enumerate(sources):
        d = dijkstra(g, indices=own, min_only=True, limit=CATCHMENT)
        closer = d < best
        best[closer], owner[closer] = d[closer], k
    catch = np.flatnonzero(owner >= 0)
    own_k, base = owner[catch], best[catch]
    print(f"catchment nodes {len(catch):,}")

    alt_any = np.full(len(catch), LIMIT)
    alt_line = np.full(len(catch), LIMIT)
    for k, (_, anyc) in enumerate(sources):
        d = dijkstra(g, indices=anyc, min_only=True, limit=LIMIT)[catch]
        other = cx[own_k] != cx[k]
        alt_any = np.where(other, np.minimum(alt_any, d), alt_any)
        line = other & shares[own_k, k]
        alt_line = np.where(line, np.minimum(alt_line, d), alt_line)

    w_all = pop[catch] + jobs[catch]
    rows = []
    for k, s in enumerate(stops):
        m = own_k == k
        w, tot = w_all[m], w_all[m].sum()
        avg = lambda x: float((w * (x[m] - base[m])).sum() / tot) if tot else float("nan")
        rows.append(dict(stop=s, name=stations[s]["name"], catchment_pop=pop[catch][m].sum(),
                         catchment_jobs=jobs[catch][m].sum(), added_line_m=avg(alt_line), added_any_m=avg(alt_any)))
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "walk_catchment.csv", index=False)
    print(out.describe().round(0).to_string())


if __name__ == "__main__":
    main()
