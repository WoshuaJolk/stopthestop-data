"""Timetable routing (RAPTOR) on the weekday GTFS schedule, complex to complex.
Travel time includes waiting at the origin and at transfers."""
import io
import zipfile

import numba as nb
import numpy as np
import pandas as pd

from analyze import gtfs_time, load_stations
from paths import GTFS, STATIONS

MAX_ROUNDS = 4  # up to 3 transfers
DEP_OFFSETS = np.arange(5, 60, 10) * 60  # departure samples within each hour, seconds
DAY = 86400
INF = np.int32(10**9)


def load_timetable(path=GTFS):
    z = zipfile.ZipFile(path)
    read = lambda n, **kw: pd.read_csv(io.BytesIO(z.read(n)), dtype=str, **kw)
    stops = read("stops.txt")
    parent = dict(zip(stops.stop_id, stops.parent_station.fillna(stops.stop_id)))
    cal = read("calendar.txt")
    weekday = set(cal[cal.monday == "1"].service_id)
    trips = read("trips.txt")
    trips = trips[trips.service_id.isin(weekday) & (trips.route_id != "SI")]
    st = read("stop_times.txt", usecols=["trip_id", "stop_id", "arrival_time", "departure_time", "stop_sequence"])
    st = st[st.trip_id.isin(set(trips.trip_id))].copy()
    st["arr"] = st.arrival_time.map(gtfs_time).astype(np.int32)
    st["dep"] = st.departure_time.map(gtfs_time).astype(np.int32)
    st["seq"] = st.stop_sequence.astype(int)
    st["parent"] = st.stop_id.map(parent)
    st = st.sort_values(["trip_id", "seq"])[["trip_id", "stop_id", "parent", "arr", "dep"]].reset_index(drop=True)
    xfer = read("transfers.txt")
    xfer = {(a, b): int(t) for a, b, t in zip(xfer.from_stop_id, xfer.to_stop_id, xfer.min_transfer_time)}
    return st, xfer


def cut_stop(st, parent, sp):
    """Remove `parent` from every trip that passes through it. The timetable itself is unchanged; `saved` records the
    seconds a rider still on board has gained, so only riders riding past the skipped stop arrive earlier. Shifting
    the timetable instead would move trains relative to sampled departure times and add large spurious wait changes."""
    first = st.trip_id.ne(st.trip_id.shift())
    last = st.trip_id.ne(st.trip_id.shift(-1))
    hit = (st.parent == parent) & ~first & ~last
    out = st.copy()
    out["saved"] = hit.astype(np.int32).groupby(st.trip_id).cumsum() * sp
    return out[~hit].reset_index(drop=True)


class Network:
    def __init__(self, st, xfer, stations, complexes=None):
        # service after midnight also runs at the start of the day
        late = st.groupby("trip_id").dep.transform("max") >= DAY
        wrap = st[late].copy()
        wrap["trip_id"] = wrap.trip_id + "~"
        wrap["arr"] -= DAY
        wrap["dep"] -= DAY
        st = pd.concat([st, wrap], ignore_index=True)

        stop_ids = sorted(st.stop_id.unique())
        sidx = {s: i for i, s in enumerate(stop_ids)}
        st = st.assign(s=st.stop_id.map(sidx).astype(np.int32))
        parent_of = st.drop_duplicates("stop_id").set_index("stop_id").parent

        # RAPTOR routes: trips with an identical stop sequence
        seqs = st.groupby("trip_id", sort=False).s.apply(tuple)
        first_dep = st.groupby("trip_id", sort=False).dep.first()
        groups = pd.DataFrame({"seq": seqs, "t0": first_dep}).sort_values("t0").groupby("seq", sort=False)
        by_trip = {tid: g for tid, g in st.groupby("trip_id", sort=False)}
        r_stop_start, r_nstops, r_stops, r_time_start, r_ntrips, arr_l, dep_l, saved_l = [], [], [], [], [], [], [], []
        n_stop_flat, n_time = 0, 0
        for seq, g in groups:
            r_stop_start.append(n_stop_flat)
            r_nstops.append(len(seq))
            r_stops.extend(seq)
            n_stop_flat += len(seq)
            r_time_start.append(n_time)
            r_ntrips.append(len(g))
            for tid in g.index:
                t = by_trip[tid]
                arr_l.append(t.arr.to_numpy())
                dep_l.append(t.dep.to_numpy())
                saved_l.append(t.saved.to_numpy() if "saved" in t else np.zeros(len(t), np.int32))
                n_time += len(seq)
        self.r_stop_start = np.array(r_stop_start, np.int32)
        self.r_nstops = np.array(r_nstops, np.int32)
        self.r_stops = np.array(r_stops, np.int32)
        self.r_time_start = np.array(r_time_start, np.int64)
        self.r_ntrips = np.array(r_ntrips, np.int32)
        self.arr = np.concatenate(arr_l).astype(np.int32)
        self.dep = np.concatenate(dep_l).astype(np.int32)
        self.saved = np.concatenate(saved_l).astype(np.int32)

        n = len(stop_ids)
        pairs = [[] for _ in range(n)]
        for r in range(len(r_nstops)):
            for k in range(r_nstops[r]):
                pairs[r_stops[r_stop_start[r] + k]].append((r, k))
        self.sr_start = np.cumsum([0] + [len(p) for p in pairs[:-1]]).astype(np.int32)
        self.sr_n = np.array([len(p) for p in pairs], np.int32)
        flat = [x for p in pairs for x in p]
        self.sr_route = np.array([x[0] for x in flat], np.int32)
        self.sr_idx = np.array([x[1] for x in flat], np.int32)

        # transfers between platforms of the same complex, including the same platform
        cx_of = [stations[parent_of[s]]["complex"] if parent_of[s] in stations else None for s in stop_ids]
        members = {}
        for i, c in enumerate(cx_of):
            if c is not None:
                members.setdefault(c, []).append(i)
        tr = [[] for _ in range(n)]
        for group in members.values():
            for a in group:
                for b in group:
                    pa, pb = parent_of[stop_ids[a]], parent_of[stop_ids[b]]
                    t = xfer.get((pa, pb), 180 if pa == pb else 300)
                    tr[a].append((b, t))
        self.tr_start = np.cumsum([0] + [len(t) for t in tr[:-1]]).astype(np.int32)
        self.tr_n = np.array([len(t) for t in tr], np.int32)
        self.tr_to = np.array([x[0] for t in tr for x in t], np.int32)
        self.tr_time = np.array([x[1] for t in tr for x in t], np.int32)

        # a fixed list keeps matrices aligned across scenarios; a cut stop's complex just has no platforms
        self.complexes = complexes if complexes is not None else sorted(members)
        ci = {c: i for i, c in enumerate(self.complexes)}
        self.stop_cx = np.array([ci.get(c, -1) if c is not None else -1 for c in cx_of], np.int32)
        self.cx_stops = [np.array(members.get(c, []), np.int32) for c in self.complexes]
        self.n_stops = n

    def travel_times(self):
        """Mean travel time in seconds [hour, origin complex, destination complex]; INF if unreachable."""
        C = len(self.complexes)
        src = np.concatenate(self.cx_stops)
        src_start = np.cumsum([0] + [len(x) for x in self.cx_stops[:-1]]).astype(np.int32)
        src_n = np.array([len(x) for x in self.cx_stops], np.int32)
        return _all_queries(C, src, src_start, src_n, DEP_OFFSETS.astype(np.int32), self.n_stops, self.stop_cx,
                            self.r_stop_start, self.r_nstops, self.r_stops, self.r_time_start, self.r_ntrips,
                            self.arr, self.dep, self.saved, self.sr_start, self.sr_n, self.sr_route, self.sr_idx,
                            self.tr_start, self.tr_n, self.tr_to, self.tr_time)


@nb.njit(cache=True)
def _query(tau, sources, n_stops, r_stop_start, r_nstops, r_stops, r_time_start, r_ntrips, arr, dep, saved,
           sr_start, sr_n, sr_route, sr_idx, tr_start, tr_n, tr_to, tr_time):
    best = np.full(n_stops, INF, np.int32)
    board = np.full(n_stops, INF, np.int32)
    marked = np.zeros(n_stops, np.bool_)
    for s in sources:
        board[s] = tau
        marked[s] = True
    n_routes = len(r_nstops)
    route_from = np.full(n_routes, -1, np.int32)
    for _ in range(MAX_ROUNDS):
        route_from[:] = -1
        any_marked = False
        for s in range(n_stops):
            if marked[s]:
                any_marked = True
                for j in range(sr_start[s], sr_start[s] + sr_n[s]):
                    r, k = sr_route[j], sr_idx[j]
                    if route_from[r] == -1 or k < route_from[r]:
                        route_from[r] = k
        if not any_marked:
            break
        board_prev = board.copy()
        marked[:] = False
        improved = np.zeros(n_stops, np.bool_)
        for r in range(n_routes):
            k0 = route_from[r]
            if k0 < 0:
                continue
            ns, s0, t0, nt = r_nstops[r], r_stop_start[r], r_time_start[r], r_ntrips[r]
            trip = -1
            saved_at_board = 0
            for k in range(k0, ns):
                s = r_stops[s0 + k]
                if trip >= 0:
                    a = arr[t0 + trip * ns + k] - (saved[t0 + trip * ns + k] - saved_at_board)
                    if a < best[s]:
                        best[s] = a
                        improved[s] = True
                bt = board_prev[s]
                if bt < INF and (trip < 0 or bt <= dep[t0 + trip * ns + k]):
                    cand, cdep = -1, INF
                    for m in range(nt):
                        d = dep[t0 + m * ns + k]
                        if d >= bt and d < cdep:
                            cand, cdep = m, d
                    if cand >= 0 and (trip < 0 or cdep < dep[t0 + trip * ns + k]):
                        trip = cand
                        saved_at_board = saved[t0 + cand * ns + k]
        for s in range(n_stops):
            if improved[s]:
                for j in range(tr_start[s], tr_start[s] + tr_n[s]):
                    t = best[s] + tr_time[j]
                    if t < board[tr_to[j]]:
                        board[tr_to[j]] = t
                        marked[tr_to[j]] = True
    return best


@nb.njit(parallel=True, cache=True)
def _all_queries(C, src, src_start, src_n, offsets, n_stops, stop_cx, r_stop_start, r_nstops, r_stops, r_time_start,
                 r_ntrips, arr, dep, saved, sr_start, sr_n, sr_route, sr_idx, tr_start, tr_n, tr_to, tr_time):
    out = np.zeros((24, C, C), np.float64)
    cnt = np.zeros((24, C, C), np.int32)
    n_off = len(offsets)
    for q in nb.prange(C * 24 * n_off):
        o = q // (24 * n_off)
        h = (q // n_off) % 24
        tau = np.int32(h * 3600 + offsets[q % n_off])
        best = _query(tau, src[src_start[o]:src_start[o] + src_n[o]], n_stops, r_stop_start, r_nstops, r_stops,
                      r_time_start, r_ntrips, arr, dep, saved, sr_start, sr_n, sr_route, sr_idx, tr_start, tr_n, tr_to,
                      tr_time)
        cx_best = np.full(C, INF, np.int32)
        for s in range(n_stops):
            c = stop_cx[s]
            if c >= 0 and best[s] < cx_best[c]:
                cx_best[c] = best[s]
        for d in range(C):
            if cx_best[d] < INF:
                out[h, o, d] += cx_best[d] - tau
                cnt[h, o, d] += 1
    res = np.full((24, C, C), np.inf)
    for h in range(24):
        for o in range(C):
            for d in range(C):
                if cnt[h, o, d] == n_off:
                    res[h, o, d] = out[h, o, d] / n_off
    return res


if __name__ == "__main__":
    import time

    stations = load_stations(STATIONS)
    st, xfer = load_timetable()
    t = time.time()
    net = Network(st, xfer, stations)
    print(f"build {time.time() - t:.1f}s: {net.n_stops} platforms, {len(net.r_nstops)} routes, {len(net.complexes)} complexes")
    t = time.time()
    T = net.travel_times()
    print(f"first run (with compile) {time.time() - t:.1f}s")
    t = time.time()
    T = net.travel_times()
    print(f"second run {time.time() - t:.1f}s; reachable share at 8am {np.isfinite(T[8]).mean():.3f}")
