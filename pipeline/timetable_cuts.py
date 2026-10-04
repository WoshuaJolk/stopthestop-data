"""For each eligible stop: remove it from the weekday timetable, route every weekday trip hour by hour, and total
the change in everyone else's door-to-door ride time (waits and transfers included), at stop times 0, 30 and 70 s.
The site interpolates between them. Writes results/timetable_cuts.csv (resumable)."""
import glob
import os

import numpy as np
import pandas as pd

from analyze import load_stations
from raptor import Network, cut_stop, load_timetable
from paths import OD_WEEKDAY, RESULTS, STATIONS

SP = (0, 30, 70)
OUT = RESULTS / "timetable_cuts.csv"


def load_weekday_od(complexes):
    ci = {c: i for i, c in enumerate(complexes)}
    files = sorted(glob.glob(f"{OD_WEEKDAY}/2026-*-h*.csv"))
    months = sorted({f.split("/")[-1][:7] for f in files})
    assert len(files) == 24 * len(months), f"incomplete weekday OD: {len(files)} files for {len(months)} months"
    R = np.zeros((24, len(complexes), len(complexes)))
    for f in files:
        h = int(f[-6:-4])
        od = pd.read_csv(f, dtype={"origin": str, "destination": str})
        for c in ("origin", "destination"):
            od[c] = od[c].astype(float).astype(int).astype(str)
        od = od[od.origin.isin(ci) & od.destination.isin(ci) & (od.origin != od.destination)]
        np.add.at(R[h], (od.origin.map(ci).to_numpy(), od.destination.map(ci).to_numpy()), od.riders.to_numpy())
    R /= 5 * len(months)  # summed over Mon-Fri day types and months -> average weekday
    print(f"weekday OD: {len(months)} months, {R.sum():,.0f} trips/day", flush=True)
    return R


def main():
    stations = load_stations(STATIONS)
    st, xfer = load_timetable()
    base_net = Network(st, xfer, stations)
    cxs = base_net.complexes
    R = load_weekday_od(cxs)
    base = base_net.travel_times()
    ok = np.isfinite(base)
    print(f"baseline rider-hours/day {(R[ok] * base[ok]).sum() / 3600:,.0f}; unreachable riders {R[~ok].sum():,.0f}", flush=True)

    elig = pd.read_csv(RESULTS / "multi_month_2026.csv", dtype={"stop": str}).stop.tolist()
    done = set(pd.read_csv(OUT, dtype={"stop": str}).stop) if os.path.exists(OUT) else set()
    ci = {c: i for i, c in enumerate(cxs)}
    for k, stop in enumerate(elig):
        if stop in done:
            continue
        cx = ci[stations[stop]["complex"]]
        keep = np.ones(len(cxs), bool)
        keep[cx] = False
        users = R[:, cx, :].sum() + R[:, :, cx].sum()
        deltas, lost = [], 0.0
        for sp in SP:
            T = Network(cut_stop(st, stop, sp), xfer, stations, cxs).travel_times()
            others = ok & keep[None, :, None] & keep[None, None, :]
            m = others & np.isfinite(T)
            deltas.append(float((R[m] * (T[m] - base[m])).sum()))
            lost = max(lost, float(R[others & ~np.isfinite(T)].sum()))
        through_eff = (deltas[1] - deltas[2]) / (SP[2] - SP[1])
        row = pd.DataFrame([dict(stop=stop, users=users, through_eff=through_eff, unreachable=lost,
                                 **{f"d{sp}_s": d for sp, d in zip(SP, deltas)})])
        row.to_csv(OUT, mode="a", header=not os.path.exists(OUT), index=False)
        if k % 20 == 0:
            print(f"{k}/{len(elig)} {stations[stop]['name']}: through {through_eff:,.0f}, "
                  f"transfer loss {deltas[0] / 3600:,.0f} h, saved at 30s {-deltas[1] / 3600:,.0f} h", flush=True)


if __name__ == "__main__":
    main()
