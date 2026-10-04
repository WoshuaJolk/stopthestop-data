"""Score subway stops by net time saved if cut. Usage: python analyze.py [year month]"""
import glob
import heapq
import io
import math
import os
import sys
import zipfile
from collections import defaultdict

import pandas as pd

from paths import GTFS, OD, RESULTS, STATIONS

SKIP_ROUTES = {"6X", "7X", "FX", "SI"}  # peak-only express variants, and SIR (not in OD data)
SAME_PLATFORM_XFER = 150.0
OTHER_XFER = 300.0
WALK_SPEED = 1.3  # m/s
DAY_START, DAY_END = 6 * 3600, 21 * 3600
BRANCH_SHARE = 0.10
SETTINGS = [(sp, ww) for sp in (45, 60) for ww in (1.0, 2.0)]


def gtfs_time(s):
    h, m, sec = s.split(":")
    return int(h) * 3600 + int(m) * 60 + int(sec)


def haversine(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def load_patterns(path):
    z = zipfile.ZipFile(path)
    read = lambda n, **kw: pd.read_csv(io.BytesIO(z.read(n)), dtype=str, **kw)
    stops = read("stops.txt")
    parent = dict(zip(stops.stop_id, stops.parent_station.fillna(stops.stop_id)))
    cal = read("calendar.txt")
    weekday = set(cal[cal.monday == "1"].service_id)
    trips = read("trips.txt")
    trips = trips[trips.service_id.isin(weekday) & ~trips.route_id.isin(SKIP_ROUTES)]
    st = read("stop_times.txt", usecols=["trip_id", "stop_id", "departure_time", "stop_sequence"])
    st = st[st.trip_id.isin(set(trips.trip_id))]
    st["t"] = st.departure_time.map(gtfs_time)
    st["seq"] = st.stop_sequence.astype(int)
    st["stop"] = st.stop_id.map(parent)
    st = st.sort_values(["trip_id", "seq"])
    by_trip = {tid: (tuple(g.stop), g.t.to_numpy()) for tid, g in st.groupby("trip_id", sort=False)}
    del st

    patterns = {}
    for (route, d), g in trips.groupby(["route_id", "direction_id"]):
        seqs = defaultdict(list)
        for tid in g.trip_id:
            if tid in by_trip and DAY_START <= by_trip[tid][1][0] < DAY_END:
                s, t = by_trip[tid]
                seqs[s].append(t)
        total = sum(len(v) for v in seqs.values())
        covered = set()
        for i, (seq, times) in enumerate(sorted(seqs.items(), key=lambda kv: -len(kv[1]))):
            # most common pattern, plus branches that serve stops it misses
            if i and (len(times) < BRANCH_SHARE * total or set(seq) <= covered):
                continue
            covered |= set(seq)
            run = [float(pd.Series([t[j + 1] - t[j] for t in times]).median()) for j in range(len(seq) - 1)]
            patterns[(route, d, i)] = (seq, run)
    return patterns


def load_stations(path):
    s = pd.read_csv(path, dtype=str)
    s["Complex ID"] = s["Complex ID"].astype(float).astype(int).astype(str)
    return {
        r["GTFS Stop ID"]: dict(complex=r["Complex ID"], name=r["Stop Name"], routes=r["Daytime Routes"],
                                 ada=int(r["ADA"]), ll=(float(r["GTFS Latitude"]), float(r["GTFS Longitude"])))
        for _, r in s.iterrows()
    }


def load_od(year, month):
    files = sorted(glob.glob(f"{OD}/{year}-{month:02d}-h*.csv"))
    if len(files) != 24:
        raise SystemExit(f"expected 24 hourly OD files, found {len(files)}")
    od = pd.concat(pd.read_csv(f, dtype={"origin": str, "destination": str}) for f in files)
    for c in ("origin", "destination"):
        od[c] = od[c].astype(float).astype(int).astype(str)
    od = od.groupby(["origin", "destination"], as_index=False).riders.sum()
    od["riders"] /= 7.0
    return od


def build_graph(patterns, stations):
    adj = defaultdict(list)  # node -> [(nbr, cost, kind)]
    nodes_by_complex = defaultdict(set)
    terminals, neighbors = set(), defaultdict(set)
    missing = set()
    for (route, *_), (seq, run) in patterns.items():
        terminals.update((seq[0], seq[-1]))
        for i, stop in enumerate(seq):
            if stop in stations:
                nodes_by_complex[stations[stop]["complex"]].add((route, stop))
            else:
                missing.add(stop)
            if i:
                adj[(route, seq[i - 1])].append(((route, stop), run[i - 1], "ride"))
                neighbors[stop].add(seq[i - 1])
                neighbors[seq[i - 1]].add(stop)
    for nodes in nodes_by_complex.values():
        for a in sorted(nodes):
            for b in sorted(nodes):
                if a[0] != b[0]:
                    adj[a].append((b, SAME_PLATFORM_XFER if a[1] == b[1] else OTHER_XFER, "xfer"))
    return adj, nodes_by_complex, terminals, neighbors, missing


def dijkstra(adj, sources):
    dist = {n: 0.0 for n in sources}
    prev = {}
    pq = [(0.0, n) for n in sorted(sources)]
    heapq.heapify(pq)
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        for v, c, _ in adj[u]:
            nd = d + c
            if nd < dist.get(v, math.inf):
                dist[v], prev[v] = nd, u
                heapq.heappush(pq, (nd, v))
    return dist, prev


def assign(od, adj, nodes_by_complex):
    users, through, transfers = defaultdict(float), defaultdict(float), defaultdict(float)
    unrouted = 0.0
    for origin, g in od.groupby("origin"):
        if origin not in nodes_by_complex:
            unrouted += g.riders.sum()
            continue
        dist, prev = dijkstra(adj, nodes_by_complex[origin])
        for dest, r in zip(g.destination, g.riders):
            if dest == origin:
                continue
            cands = sorted(n for n in nodes_by_complex.get(dest, ()) if n in dist)
            if not cands:
                unrouted += r
                continue
            path = [min(cands, key=dist.get)]
            while path[-1] in prev:
                path.append(prev[path[-1]])
            path.reverse()
            users[path[0][1]] += r
            users[path[-1][1]] += r
            for i in range(1, len(path) - 1):
                a, n, b = path[i - 1], path[i], path[i + 1]
                if a[0] == n[0] == b[0]:
                    through[n[1]] += r
                elif a[0] == n[0] != b[0]:
                    transfers[n[1]] += r
    return users, through, transfers, unrouted


def load_street(path=RESULTS / "walk_street.csv"):
    if not os.path.exists(path):
        return {}
    w = pd.read_csv(path, dtype=str).dropna()
    return {(a, b): float(m) for a, b, m in zip(w["from"], w["to"], w.meters)}


def load_entrance_walk(path=RESULTS / "walk_entrance.csv"):
    if not os.path.exists(path):
        return {}
    w = pd.read_csv(path, dtype={"stop": str, "to_stop": str}).dropna()
    # mean over the stop's entrances; walk_to is the neighbor most entrances lead to
    return {s: (g.meters.mean(), g.to_stop.mode().iloc[0], len(g)) for s, g in w.groupby("stop")}


def load_catchment(path=RESULTS / "walk_catchment.csv"):
    if not os.path.exists(path):
        return {}
    c = pd.read_csv(path, dtype={"stop": str}).dropna(subset=["added_line_m"])
    return {s: (a, b) for s, a, b in zip(c.stop, c.added_line_m, c.added_any_m)}


def score(stations, users, through, transfers, terminals, neighbors, nodes_by_complex):
    street, entrance, catchment = load_street(), load_entrance_walk(), load_catchment()
    hubs = {c for c, nodes in nodes_by_complex.items() if len({s for _, s in nodes}) > 1}
    rows = []
    for stop, nbrs in neighbors.items():
        if stop not in stations:
            continue
        info = stations[stop]
        # street distance where routed, else straight line
        walk, nearest = min((street.get((stop, n), haversine(info["ll"], stations[n]["ll"])), n) for n in nbrs if n in stations)
        point_m = walk
        if stop in entrance:
            walk, nearest, _ = entrance[stop]
        station_m = walk
        # population-weighted added walk to the next station on the same line
        walk, any_m = catchment.get(stop, (walk, float("nan")))
        line_m = haversine(info["ll"], stations[nearest]["ll"])
        rows.append(dict(stop=stop, name=info["name"], routes=info["routes"], complex=info["complex"],
                         users=users[stop], through=through[stop], transfers=transfers[stop],
                         walk_m=walk, any_m=any_m, station_m=station_m, point_m=point_m, line_m=line_m, entrances=stop in entrance, street=(stop, nearest) in street, walk_to=stations[nearest]["name"], ada=info["ada"],
                         walk_to_ada=stations[nearest]["ada"],
                         hub=info["complex"] in hubs, terminal=stop in terminals))
    df = pd.DataFrame(rows)
    for sp, ww in SETTINGS:
        tag = f"sp{sp}_ww{ww:g}"
        keep = df.through * sp
        cut = df.users * df.walk_m / WALK_SPEED * ww
        df[f"wait_{tag}"] = keep / 3600  # rider-hours per day
        df[f"walk_{tag}"] = cut / 3600
        df[f"net_{tag}"] = df[f"wait_{tag}"] - df[f"walk_{tag}"]
    return df


def load_network():
    stations = load_stations(STATIONS)
    patterns = load_patterns(GTFS)
    adj, nodes_by_complex, terminals, neighbors, missing = build_graph(patterns, stations)
    print(f"patterns {len(patterns)}, complexes in graph {len(nodes_by_complex)}, GTFS stops not in stations file: {sorted(missing)}")
    return stations, adj, nodes_by_complex, terminals, neighbors


def run_month(net, year, month):
    stations, adj, nodes_by_complex, terminals, neighbors = net
    od = load_od(year, month)
    users, through, transfers, unrouted = assign(od, adj, nodes_by_complex)
    print(f"{year}-{month:02d}: daily trips {od.riders.sum():,.0f}, unrouted {unrouted:,.0f}")
    df = score(stations, users, through, transfers, terminals, neighbors, nodes_by_complex)
    elig = df[~df.hub & ~df.terminal].copy()
    for t in TAGS:
        elig[f"rank_{t}"] = elig[f"net_{t}"].rank(ascending=False).astype(int)
    return df, elig


TAGS = [f"sp{sp}_ww{ww:g}" for sp, ww in SETTINGS]


def main():
    year, month = (int(a) for a in sys.argv[1:3]) if len(sys.argv) > 2 else (2026, 5)
    df, elig = run_month(load_network(), year, month)
    tags = TAGS
    rk = [f"rank_{t}" for t in tags]
    elig["worst_rank"] = elig[rk].max(axis=1)
    elig = elig.sort_values(f"rank_{tags[0]}")
    df.sort_values(f"net_{tags[0]}", ascending=False).to_csv(RESULTS / f"all_stops_{year}-{month:02d}.csv", index=False)
    elig.to_csv(RESULTS / f"ranked_{year}-{month:02d}.csv", index=False)
    print(f"stops scored {len(df)}, eligible {len(elig)} (excluded {df.hub.sum()} hub, {df.terminal.sum()} terminal)")
    cols = ["stop", "name", "routes", "users", "through", "walk_m"] + [f"net_{tags[0]}", f"net_{tags[-1]}"] + rk + ["worst_rank"]
    with pd.option_context("display.width", 250, "display.max_columns", 30, "display.float_format", "{:,.0f}".format):
        print(elig[cols].head(25).to_string(index=False))
        stable = elig[elig.worst_rank <= 25]
        print(f"\nstops in top 25 under all {len(tags)} settings: {len(stable)}")


if __name__ == "__main__":
    main()
