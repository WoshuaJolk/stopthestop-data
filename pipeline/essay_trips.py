"""Who wins and who walks if 3 Av closes, at a 50 s stop cost: per-trip change in travel time (Exhibit G), hours
saved by station (Exhibit D), and example trips that save far more than 50 s (Exhibit C).
Needs results/third_ave/walkshed.json from essay_walkshed.py. Writes results/third_ave/trip_changes.json."""
import json

import numpy as np

from analyze import load_stations
from paths import RESULTS, STATIONS
from raptor import Network, _query, cut_stop, load_timetable
from timetable_cuts import load_weekday_od

STOP = "L05"
SP = 50
WALK_SPEED = 1.3
OUT = RESULTS / "third_ave"


def main():
    stations = load_stations(STATIONS)
    st, xfer = load_timetable()
    base_net = Network(st, xfer, stations)
    cxs = base_net.complexes
    ci = {c: i for i, c in enumerate(cxs)}
    R = load_weekday_od(cxs)
    base = base_net.travel_times()
    T = {sp: Network(cut_stop(st, STOP, sp), xfer, stations, cxs).travel_times() for sp in (30, 70)}
    with np.errstate(invalid="ignore"):  # inf - inf for unreachable pairs
        T50 = T[30] + (T[70] - T[30]) * (SP - 30) / 40
    c3 = ci[stations[STOP]["complex"]]
    keep = np.ones(len(cxs), bool)
    keep[c3] = False
    m = np.isfinite(base) & np.isfinite(T50) & keep[None, :, None] & keep[None, None, :]
    delta = np.where(m, T50 - base, 0.0)

    d, w = delta[m].ravel(), R[m].ravel()
    edges = np.arange(-300, 61, 10)
    hist, _ = np.histogram(np.clip(d, -299, 59), bins=edges, weights=w)
    unchanged = w[np.abs(d) < 5].sum()
    stats = dict(train_hours_saved=round(-(R * delta).sum() / 3600), trips_changed=round(w[np.abs(d) >= 5].sum()),
                 trips_unchanged=round(unchanged), trips_saving_over_60s=round(w[d < -60].sum()),
                 trips_slower=round(w[d > 5].sum()))
    print(stats)

    # the stop's own riders: extra walking time, distributed like the walkshed's residents and jobs
    cat = json.load(open(OUT / "walkshed.json"))
    users = R[:, c3, :].sum() + R[:, :, c3].sum()
    pw = np.array([p[2] for p in cat["points"]], float)
    pe = np.array([p[3] for p in cat["points"]], float) / WALK_SPEED
    wedges = np.arange(0, 301, 10)
    whist, _ = np.histogram(np.clip(pe, 0, 299), bins=wedges, weights=pw / pw.sum() * users)

    # hours saved by station, half credited to each end of the trip
    saved = -(R * delta).sum(axis=0)
    by = saved.sum(axis=1) / 2 + saved.sum(axis=0) / 2
    name = {}
    for v in stations.values():
        name.setdefault(v["complex"], (v["name"], set()))[1].update(v["routes"].split())
    order = np.argsort(-by)
    top = [dict(name=name[cxs[i]][0], routes=" ".join(sorted(name[cxs[i]][1])), hours=round(by[i] / 3600, 1))
           for i in order[:12]]

    # Brooklyn L origins to Manhattan destinations whose saving at an 8-8:30am departure is 4+ minutes
    cut_net = Network(cut_stop(st, STOP, SP), xfer, stations, cxs)
    args = lambda n: (n.n_stops, n.r_stop_start, n.r_nstops, n.r_stops, n.r_time_start, n.r_ntrips, n.arr, n.dep,
                      n.saved, n.sr_start, n.sr_n, n.sr_route, n.sr_idx, n.tr_start, n.tr_n, n.tr_to, n.tr_time)
    arrive = lambda n, o, dst, tau: min((_query(np.int32(tau), n.cx_stops[o], *args(n))[s] for s in n.cx_stops[dst]),
                                        default=1 << 30)
    cands = []
    for org in ("L08", "L10", "L11", "L12", "L13", "L14", "L15", "L16", "L17"):
        o = ci[stations[org]["complex"]]
        for dest in ("611", "610", "404", "13", "628", "623"):
            if dest not in ci:
                continue
            dd = ci[dest]
            for tau in range(8 * 3600, 8 * 3600 + 1800, 60):
                a0, a1 = arrive(base_net, o, dd, tau), arrive(cut_net, o, dd, tau)
                if a0 < 1 << 29 and a0 - a1 >= 240:
                    cands.append(dict(saved_s=int(a0 - a1), origin=org, destination_complex=dest, depart=tau,
                                      arrive_today=int(a0), arrive_without=int(a1), riders_8am_hour=float(R[8, o, dd])))
    cands.sort(key=lambda c: (-c["riders_8am_hour"], -c["saved_s"]))

    out = dict(stats=stats,
               hist=dict(edges=edges.tolist(), riders=hist.round().tolist(), unchanged=round(unchanged)),
               walk=dict(edges=wedges.tolist(), riders=whist.round().tolist()),
               top=top, topShare=round(by[order[:12]].sum() / by.sum(), 3), totalHours=round(by.sum() / 3600),
               examples=cands[:8])
    json.dump(out, open(OUT / "trip_changes.json", "w"), indent=1)


if __name__ == "__main__":
    main()
