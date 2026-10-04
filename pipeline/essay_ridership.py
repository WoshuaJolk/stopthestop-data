"""Ridership at 3 Av and its neighbors: entries plus exits at morning rush (the "5x and 17x"), and L riders getting
on, off, and riding through each stop from 5 to 6pm (Exhibit B). Writes results/third_ave/ridership.json."""
import glob
import json
import os
from collections import defaultdict

import pandas as pd

from analyze import dijkstra, load_network
from paths import OD_WEEKDAY, RESULTS

L_STOPS = ("L03", "L05", "L06")  # Union Sq, 3 Av, 1 Av
COMPLEX = {"3 Av": "118", "1 Av": "119", "14 St-Union Sq (all lines)": "602"}


def weekday_od(hours):
    files = [f for f in sorted(glob.glob(f"{OD_WEEKDAY}/2026-*-h*.csv")) if int(f[-6:-4]) in hours]
    months = len({os.path.basename(f)[:7] for f in files})
    od = pd.concat(pd.read_csv(f, dtype={"origin": str, "destination": str}) for f in files)
    for c in ("origin", "destination"):
        od[c] = od[c].astype(float).astype(int).astype(str)
    od = od[od.origin != od.destination].groupby(["origin", "destination"], as_index=False).riders.sum()
    od["riders"] /= 5 * months
    return od


def entries_exits(od, cx):
    return od.riders[od.origin == cx].sum() + od.riders[od.destination == cx].sum()


def rush():
    out = {}
    for label, hours in (("7am", [7]), ("8am", [8]), ("7-9am", [7, 8])):
        od = weekday_od(hours)
        n = {k: entries_exits(od, c) for k, c in COMPLEX.items()}
        out[label] = {**{k: round(v) for k, v in n.items()},
                      **{f"{k} / 3 Av": round(v / n["3 Av"], 1) for k, v in n.items() if k != "3 Av"}}
    return out


def l_flow(hour):
    """On the static schedule graph from analyze.py (shortest paths, not the timetable)."""
    _, adj, nbc, _, _ = load_network()
    od = weekday_od([hour])
    on, off, thr = defaultdict(float), defaultdict(float), defaultdict(float)
    for origin, g in od.groupby("origin"):
        if origin not in nbc:
            continue
        dist, prev = dijkstra(adj, nbc[origin])
        for dest, r in zip(g.destination, g.riders):
            cands = sorted(n for n in nbc.get(dest, ()) if n in dist)
            if not cands:
                continue
            path = [min(cands, key=dist.get)]
            while path[-1] in prev:
                path.append(prev[path[-1]])
            path.reverse()
            for i, n in enumerate(path):
                if n[1] not in L_STOPS:
                    continue
                nxt = path[i + 1] if i + 1 < len(path) else None
                prv = path[i - 1] if i else None
                if nxt and nxt[0] == n[0] and (prv is None or prv[0] != n[0]):
                    on[n[1]] += r
                if prv and prv[0] == n[0] and (nxt is None or nxt[0] != n[0]):
                    off[n[1]] += r
                if prv and nxt and prv[0] == n[0] == nxt[0]:
                    thr[n[1]] += r
    return {s: dict(on=round(on[s]), off=round(off[s]), through=round(thr[s])) for s in L_STOPS}


def main():
    out = dict(rush_entries_exits=rush(), l_riders_5pm=l_flow(17))
    print(json.dumps(out, indent=1))
    (RESULTS / "third_ave").mkdir(exist_ok=True)
    json.dump(out, open(RESULTS / "third_ave" / "ridership.json", "w"), indent=1)


if __name__ == "__main__":
    main()
