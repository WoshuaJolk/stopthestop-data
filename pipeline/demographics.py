"""Who lives near, and who rides from, each station complex: age, disability, income, schools, fare classes.
Writes results/demographics.csv and results/community.json, and prints how 3 Av compares."""
import json
import os
import re
import sys

import numpy as np
import pandas as pd
import requests
from dbfread import DBF
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from analyze import load_stations
from catchment import BBOX, CATCHMENT, load_network, xy
from paths import BLOCKS, DATA, RESULTS, STATIONS
from walk_entrances import load_entrances

DIR = DATA / "demo"
ACS_YEAR = 2024  # 5-year, 2020-2024, on 2020 tracts and block groups
ACS_URL = "https://www2.census.gov/programs-surveys/acs/summary_file/{y}/table-based-SF/data/5YRData/acsdt5y{y}-{t}.dat"
ACS_TABLES = ["b01001", "c17002", "b19001", "b18101", "b18105", "b14001", "b11007", "b03002", "b25044",
              "c16001", "b05002"]
COUNTIES = ("36005", "36047", "36061", "36081", "36085")
FARES_URL = "https://data.ny.gov/resource/5wq4-mkjj.json"
FARE_MONTHS = [(2026, m) for m in range(1, 9)]  # same months as the OD data
FACDB_URL = "https://data.cityofnewyork.us/resource/ji82-xba5.json"
RADIUS = 500.0  # m, second catchment definition: everyone within this walk, whichever station is nearest
MIN_POP = 1000  # complexes with fewer catchment residents are left out of rate comparisons
TARGET = "118"  # 3 Av
NEIGHBORS = {"Union Sq": "602", "1 Av": "119"}  # where 3 Av's riders would walk

INCOME_EDGES = [0, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 75, 100, 125, 150, 200]  # $k, B19001 bins


def fetch_acs():
    for t in ACS_TABLES:
        out = f"{DIR}/acs_{t}.csv"
        if os.path.exists(out):
            continue
        keep = tuple(f"{lvl}00000US{c}" for lvl in ("14", "15") for c in COUNTIES)
        with requests.get(ACS_URL.format(y=ACS_YEAR, t=t), stream=True, timeout=300) as r, open(out + ".tmp", "w") as f:
            r.raise_for_status()
            r.encoding = "utf-8"
            for i, line in enumerate(r.iter_lines(decode_unicode=True)):
                if i == 0 or line.startswith(keep):
                    f.write(line + "\n")
        os.replace(out + ".tmp", out)
        print(f"acs {t} done", flush=True)


def fetch_fares():
    out = f"{DIR}/fares.csv"
    if os.path.exists(out):
        return
    rows = []
    for y, m in FARE_MONTHS:
        end = f"{y + (m == 12)}-{m % 12 + 1:02d}-01T00:00:00"
        params = {"$select": "station_complex_id,fare_class_category,sum(ridership) as riders",
                  "$where": f"transit_timestamp >= '{y}-{m:02d}-01T00:00:00' AND transit_timestamp < '{end}'",
                  "$group": "station_complex_id,fare_class_category", "$limit": 50000}
        r = requests.get(FARES_URL, params=params, timeout=600)
        r.raise_for_status()
        rows += [dict(p, month=m) for p in r.json()]
        print(f"fares {y}-{m:02d} done", flush=True)
    pd.DataFrame(rows).to_csv(out, index=False)


def fetch_facilities():
    out = f"{DIR}/facilities.csv"
    if os.path.exists(out):
        return
    params = {"$select": "facname,facgroup,facsubgrp,factype,capacity,captype,address,latitude,longitude",
              "$where": "latitude IS NOT NULL", "$limit": 100000}
    r = requests.get(FACDB_URL, params=params, timeout=600)
    r.raise_for_status()
    pd.DataFrame(r.json()).to_csv(out, index=False)


def load_complexes():
    s = pd.read_csv(STATIONS, dtype=str)
    s["Complex ID"] = s["Complex ID"].astype(float).astype(int).astype(str)
    g = s.groupby("Complex ID")
    return pd.DataFrame({
        "name": g["Stop Name"].agg(lambda x: " / ".join(dict.fromkeys(x))),
        "routes": g["Daytime Routes"].agg(lambda x: " ".join(sorted(set(" ".join(x).split())))),
        "borough": g["Borough"].first(),
        "ada": g["ADA"].agg(lambda x: "yes" if set(x) == {"1"} else "no" if set(x) == {"0"} else "partial"),
        "lat": g["GTFS Latitude"].agg(lambda x: x.astype(float).mean()),
        "lon": g["GTFS Longitude"].agg(lambda x: x.astype(float).mean()),
    })


def load_blocks():
    rows = [(r["GEOID20"], float(r["INTPTLON20"]), float(r["INTPTLAT20"]), r["POP20"])
            for r in DBF(str(BLOCKS), load=False) if r["GEOID20"][:5] in COUNTIES]
    b = pd.DataFrame(rows, columns=["geoid", "lon", "lat", "pop"])
    inside = b[(b["pop"] > 0) & (b.lon >= BBOX[0]) & (b.lon <= BBOX[2]) & (b.lat >= BBOX[1]) & (b.lat <= BBOX[3])].reset_index(drop=True)
    return inside, int(b["pop"].sum())


def ownership(cx, blocks, fac):
    """Nearest complex by street walk for every block and facility, plus (complex, block) pairs within RADIUS."""
    cache = f"{DIR}/owner.npz"
    if os.path.exists(cache):
        z = np.load(cache)
        return z["b_owner"], z["b_dist"], z["b_next"], z["pairs"], z["f_owner"], z["f_dist"], z["f_next"]
    stations = load_stations(STATIONS)
    _, by_complex = load_entrances(stations)
    g, p = load_network()
    tree = cKDTree(p)
    bnode = tree.query(xy(blocks.lon, blocks.lat))[1]
    fnode = tree.query(xy(fac.longitude, fac.latitude))[1]
    best, owner, pairs = np.full(len(p), np.inf), np.full(len(p), -1), []
    second = np.full(len(p), np.inf)  # walk to the next-nearest complex
    for k, c in enumerate(cx.index):
        pts = by_complex.get(c) or [(cx.lat[c], cx.lon[c])]
        src = np.unique(tree.query(xy([v[1] for v in pts], [v[0] for v in pts]))[1])
        d = dijkstra(g, indices=src, min_only=True, limit=CATCHMENT)
        second = np.minimum(second, np.maximum(best, d))
        closer = d < best
        best[closer], owner[closer] = d[closer], k
        near = np.flatnonzero(d[bnode] <= RADIUS)
        pairs.append(np.column_stack([np.full(len(near), k), near]))
    pairs = np.vstack(pairs)
    np.savez(cache, b_owner=owner[bnode], b_dist=best[bnode], b_next=second[bnode], pairs=pairs, f_owner=owner[fnode],
             f_dist=best[fnode], f_next=second[fnode])
    return owner[bnode], best[bnode], second[bnode], pairs, owner[fnode], best[fnode], second[fnode]


def acs_counts():
    """Named counts per ACS geography, from the downloaded tables."""
    def table(t):
        d = pd.read_csv(f"{DIR}/acs_{t}.csv", sep="|", dtype=str).set_index("GEO_ID")
        d = d[[c for c in d.columns if "_E" in c]].apply(pd.to_numeric, errors="coerce").fillna(0).clip(lower=0)
        d.columns = [int(c.split("_E")[1]) for c in d.columns]
        return d
    cols = lambda d, ids: d[list(ids)].sum(axis=1)
    age, pov, inc, dis, amb, enr, alone, race, cars, lang, born = (table(t) for t in ACS_TABLES)
    bg = pd.DataFrame({
        "pop": age[1], "under5": cols(age, (3, 27)), "under18": cols(age, (3, 4, 5, 6, 27, 28, 29, 30)),
        "age65": cols(age, (*range(20, 26), *range(44, 50))), "age75": cols(age, (23, 24, 25, 47, 48, 49)),
        "age18_24": cols(age, (7, 8, 9, 10, 31, 32, 33, 34)),
        "pov_univ": pov[1], "pov": cols(pov, (2, 3)), "pov200": cols(pov, range(2, 8)),
        "hh": inc[1], "hh_u25": cols(inc, range(2, 6)), "hh_u50": cols(inc, range(2, 11)),
        **{f"inc{i}": inc[i] for i in range(2, 18)},
        "race_univ": race[1], "white": race[3], "black": race[4], "asian": race[6], "hispanic": race[12],
        "hh_cars": cars[1], "no_car": cols(cars, (3, 10)),
    })
    tract = pd.DataFrame({
        "dis_univ": dis[1], "dis": cols(dis, (4, 7, 10, 13, 16, 19, 23, 26, 29, 32, 35, 38)),
        "dis65": cols(dis, (16, 19, 35, 38)), "dis65_univ": cols(dis, (15, 18, 34, 37)),
        "college": cols(enr, (8, 9)), "enr_univ": enr[1], "hh_tract": alone[1], "alone65": alone[3],
        "lang_univ": lang[1], "limited_english": cols(lang, range(5, 39, 3)),
        "born_univ": born[1], "foreign_born": born[13],
        "amb_univ": amb[1], "amb": cols(amb, (4, 7, 10, 13, 16, 20, 23, 26, 29, 32)),
    })
    pick = lambda d, lvl: d[d.index.str.startswith(f"{lvl}00000US")].rename(index=lambda x: x.split("US")[1])
    return pick(bg, "15"), pick(tract, "14")


def to_blocks(blocks, bg, tract):
    """Spread each block group's and tract's ACS counts over its blocks by 2020 population."""
    parts = []
    for acs, n in ((bg, 12), (tract, 11)):
        key = blocks.geoid.str[:n]
        share = blocks["pop"] / blocks.groupby(key)["pop"].transform("sum")
        parts.append(acs.reindex(key).fillna(0).reset_index(drop=True).mul(share, axis=0))
    return pd.concat(parts, axis=1)


def pooled_median_income(c):
    bins = c[[f"inc{i}" for i in range(2, 18)]].to_numpy()
    cum = np.cumsum(bins, axis=1)
    half = cum[:, -1] / 2
    out = np.full(len(c), np.nan)
    for r in range(len(c)):
        if half[r] <= 0:
            continue
        j = int(np.searchsorted(cum[r], half[r]))
        if j >= len(INCOME_EDGES) - 1:
            out[r] = 200  # top bin is open-ended
            continue
        lo, hi = INCOME_EDGES[j], INCOME_EDGES[j + 1]
        out[r] = lo + (hi - lo) * (half[r] - (cum[r, j - 1] if j else 0)) / bins[r, j]
    return out


def rates(c):
    r = pd.DataFrame(index=c.index)
    r["residents"] = c["pop"]
    r["pct_65plus"] = 100 * c.age65 / c["pop"]
    r["pct_75plus"] = 100 * c.age75 / c["pop"]
    r["pct_under18"] = 100 * c.under18 / c["pop"]
    r["pct_under5"] = 100 * c.under5 / c["pop"]
    r["pct_18_24"] = 100 * c.age18_24 / c["pop"]
    r["pct_college"] = 100 * c.college / c.enr_univ
    r["pct_65_alone_hh"] = 100 * c.alone65 / c.hh_tract
    r["pct_disabled_65plus"] = 100 * c.dis65 / c.dis65_univ
    r["pct_disabled"] = 100 * c.dis / c.dis_univ
    r["pct_walking_difficulty"] = 100 * c.amb / c.amb_univ
    r["pct_poverty"] = 100 * c["pov"] / c.pov_univ
    r["pct_under_2x_poverty"] = 100 * c.pov200 / c.pov_univ
    r["pct_hh_under_25k"] = 100 * c.hh_u25 / c.hh
    r["median_hh_income_k"] = pooled_median_income(c)
    # people of color: everyone except non-Hispanic white alone, the FTA Title VI definition of minority
    r["pct_people_of_color"] = 100 * (1 - c.white / c.race_univ)
    r["pct_black"] = 100 * c.black / c.race_univ
    r["pct_hispanic"] = 100 * c.hispanic / c.race_univ
    r["pct_asian"] = 100 * c.asian / c.race_univ
    r["pct_white"] = 100 * c.white / c.race_univ
    r["pct_limited_english"] = 100 * c.limited_english / c.lang_univ
    r["pct_foreign_born"] = 100 * c.foreign_born / c.born_univ
    r["pct_hh_no_car"] = 100 * c.no_car / c.hh_cars
    r["n_65plus"], r["n_under18"], r["n_disabled"] = c.age65, c.under18, c.dis
    r["n_walking_difficulty"], r["n_poverty"], r["n_65_alone_hh"] = c.amb, c["pov"], c.alone65
    return r


FAC_KINDS = {
    "schools_k12": lambda f: (f.facgroup == "SCHOOLS (K-12)") & ~f.facsubgrp.str.startswith("GED"),
    "special_ed_schools": lambda f: f.facsubgrp == "PUBLIC AND PRIVATE SPECIAL EDUCATION SCHOOLS",
    "daycare_prek": lambda f: f.facgroup == "DAY CARE AND PRE-KINDERGARTEN",
    "hospitals": lambda f: f.factype == "HOSPITAL",
    "hospital_clinics": lambda f: f.factype == "HOSPITAL EXTENSION CLINIC",
    "nursing_homes": lambda f: f.facsubgrp == "RESIDENTIAL HEALTH CARE",
    "senior_centers": lambda f: f.facsubgrp == "SENIOR SERVICES",
    "disability_programs": lambda f: f.facsubgrp == "PROGRAMS FOR PEOPLE WITH DISABILITIES",
}


def facility_counts(fac, n):
    out = pd.DataFrame(index=range(n))
    owned = fac[fac.owner >= 0]
    for kind, test in FAC_KINDS.items():
        out[kind] = owned[test(owned)].groupby("owner").size().reindex(out.index).fillna(0)
    seats = owned[(owned.facgroup == "SCHOOLS (K-12)") & (owned.captype == "seats")]
    out["public_school_seats"] = seats.groupby("owner").capacity.sum().reindex(out.index).fillna(0)
    return out


def fare_shares(days):
    f = pd.read_csv(f"{DIR}/fares.csv", dtype={"station_complex_id": str})
    cat = f.fare_class_category.str.split(" - ").str[1]
    t = f.groupby(["station_complex_id", cat]).riders.sum().unstack(fill_value=0)
    tot = t.sum(axis=1)
    return pd.DataFrame({
        "entries_per_day": tot / days,
        "ride_pct_senior_disability": 100 * t["Seniors & Disability"] / tot,
        "ride_pct_fair_fares": 100 * t["Fair Fare"] / tot,
        "ride_pct_student": 100 * t["Students"] / tot,
        "ride_senior_disability_per_day": t["Seniors & Disability"] / days,
        "ride_fair_fares_per_day": t["Fair Fare"] / days,
        "ride_student_per_day": t["Students"] / days,
    })


def report(df, base, radius):
    top = pd.read_csv(RESULTS / "ranking.csv", dtype=str).head(25)
    stations = load_stations(STATIONS)
    groups = {
        "all": df.index,
        "Manhattan": df.index[df.borough == "M"],
        "L line": df.index[df.routes.str.split().map(lambda r: "L" in r)],
        "top-25 cuts": pd.Index(top.stop.map(lambda s: stations[s]["complex"]).unique()),
    }
    t = df.loc[TARGET]
    print(f"\n3 Av (L): {t.residents:,.0f} residents nearest to it, {t.entries_per_day:,.0f} entries/day, wheelchair accessible: {t.ada}")
    print("rank 1 = highest. Rates use complexes with at least", MIN_POP, "catchment residents.\n")
    head = f"{'':28}{'3 Av':>8}" + "".join(f"{n:>10}" for n in NEIGHBORS) + f"{'NYC':>8}{'Manh':>8}" + "".join(f"{g + ' rank':>18}{'median':>10}" for g in groups)

    def table(title, metrics, src, bases=True, min_pop=True):
        print(title + "\n" + head)
        for m in metrics:
            line = f"{m:28}{src.loc[TARGET, m]:8,.1f}"
            line += "".join(f"{src.loc[c, m]:10,.1f}" for c in NEIGHBORS.values())
            line += "".join(f"{base.loc[b, m]:8,.1f}" if bases else f"{'':8}" for b in ("NYC", "Manhattan"))
            for ids in groups.values():
                v = src.loc[src.index.intersection(ids), m]
                if min_pop:
                    v = v[src.residents.reindex(v.index) >= MIN_POP]
                v = v.dropna()
                rank = int((v > src.loc[TARGET, m]).sum()) + 1
                line += f"{f'{rank} of {len(v)}':>18}{v.median():10,.1f}"
            print(line)
        print()

    res = [c for c in df.columns if c.startswith("pct_")] + ["median_hh_income_k"]
    table("RESIDENTS whose nearest station it is (share of residents)", res, df)
    table(f"RESIDENTS within a {RADIUS:.0f} m walk, nearest or not (robustness check)", res, radius)
    table("RESIDENTS affected, headcount", ["residents", "n_65plus", "n_under18", "n_disabled", "n_walking_difficulty", "n_poverty"],
          df, bases=False, min_pop=False)
    table("RIDERS entering, by fare class", [c for c in df.columns if c.startswith("ride_")], df, bases=False, min_pop=False)
    table("FACILITIES nearest to it", [*FAC_KINDS, "public_school_seats"], df, bases=False, min_pop=False)


SMALL = re.compile(r"\b(Of|And|At|For|The|In)\b")
KIND_LABEL = {"schools_k12": "School", "daycare_prek": "Day care", "hospitals": "Hospital", "hospital_clinics": "Hospital clinic"}


def pretty(name):
    t = SMALL.sub(lambda m: m.group().lower(), name.title().replace("'S", "'s").replace("Nyu", "NYU").replace("Ps ", "PS ").replace("Learningspring", "LearningSpring"))
    return t[0].upper() + t[1:]


def export_community(df, base, counts, fac, k, blocks, b_owner, b_dist, b_next, nyc_pop):
    """The numbers behind the site's /community page."""
    on_l = df.routes.str.split().map(lambda r: "L" in r)

    def row(m, src, bases=False):
        v = src[m].dropna()
        r = {"av3": df.at[TARGET, m], "unionSq": df.at["602", m], "av1": df.at["119", m], "median": v.median(),
             "lMedian": v[on_l.reindex(v.index)].median()}
        if bases:
            r |= {"manhattan": base.at["Manhattan", m], "nyc": base.at["NYC", m]}
        r = {a: round(float(b), 1) for a, b in r.items()}
        return r | {"rank": int((v > df.at[TARGET, m]).sum()) + 1, "of": len(v)}

    rated = df[df.residents >= MIN_POP]
    res = ["pct_65plus", "pct_75plus", "pct_65_alone_hh", "pct_under18", "pct_18_24", "pct_college", "pct_disabled",
           "pct_disabled_65plus", "pct_walking_difficulty", "pct_poverty", "pct_hh_under_25k", "median_hh_income_k", "pct_people_of_color",
           "pct_black", "pct_hispanic", "pct_asian", "pct_white", "pct_limited_english", "pct_foreign_born", "pct_hh_no_car"]
    cnt = ["residents", "n_65plus", "n_65_alone_hh", "n_disabled", "n_walking_difficulty", "n_poverty", "n_under18",
           "schools_k12", "public_school_seats"]
    rid = ["entries_per_day"] + [c for c in df.columns if c.startswith("ride_")]

    m = b_owner == k
    w = blocks["pop"][m]
    after = float((b_next[m] * w).sum() / w.sum())
    farther = nyc_pop - int(blocks["pop"][b_dist <= after].sum())
    distance = dict(now=round(float((b_dist[m] * w).sum() / w.sum())), after=round(after), farther=farther,
                    fartherPct=round(100 * farther / nyc_pop, 1), nycPop=nyc_pop)

    mine = fac[fac.owner == k].copy()
    mine["kind"] = ""
    for kind, label in KIND_LABEL.items():
        mine.loc[FAC_KINDS[kind](mine) & (mine.kind == ""), "kind"] = label
    mine = mine[mine.kind != ""]
    places = []
    for (kind, address), g in mine.groupby(["kind", "address"], sort=False):
        name = pretty(g.facname.iloc[0]) if len(g) == 1 else f"{len(g)} schools at {pretty(address)}"
        places.append(dict(name=name, kind=kind, seats=int(g.capacity.sum()), walk=round(float(g.dist.min())),
                           next=round(float(g.next.min()))))
    places.sort(key=lambda p: p["walk"])

    # residents nearest every other L stop, pooled: a stand-in for the riders who pass through 3 Av
    rest = df.index[on_l & (df.index != TARGET)]
    pooled = rates(counts.loc[rest].sum().to_frame().T).iloc[0]
    line = dict(stations=len(rest), **{x: round(float(pooled[x]), 1) for x in ["residents", *res]})

    out = dict(residents={x: row(x, rated, True) for x in res}, counts={x: row(x, df) for x in cnt},
               riders={x: row(x, df) for x in rid}, distance=distance, places=places, line=line)
    json.dump(out, open(RESULTS / "community.json", "w"), indent=1)


def main():
    os.makedirs(DIR, exist_ok=True)
    fetch_acs()
    fetch_fares()
    fetch_facilities()
    cx = load_complexes()
    blocks, nyc_pop = load_blocks()
    fac = pd.read_csv(f"{DIR}/facilities.csv")
    fac["capacity"] = pd.to_numeric(fac.capacity, errors="coerce").fillna(0)
    b_owner, b_dist, b_next, pairs, fac["owner"], fac["dist"], fac["next"] = ownership(cx, blocks, fac)

    bg, tract = acs_counts()
    per_block = to_blocks(blocks, bg, tract)
    owned = b_owner >= 0
    counts = per_block[owned].groupby(b_owner[owned]).sum().reindex(range(len(cx))).fillna(0)
    near = per_block.iloc[pairs[:, 1]].groupby(pairs[:, 0]).sum().reindex(range(len(cx))).fillna(0)
    days = sum(pd.Period(f"{y}-{m:02d}").days_in_month for y, m in FARE_MONTHS)

    df = pd.concat([rates(counts), facility_counts(fac, len(cx))], axis=1).set_index(cx.index)
    df = cx[["name", "routes", "borough", "ada"]].join(df).join(fare_shares(days))
    radius = rates(near).set_index(cx.index)
    df.join(radius.add_prefix(f"r{RADIUS:.0f}_")).to_csv(RESULTS / "demographics.csv")

    whole = lambda ids: pd.concat([bg[bg.index.str[:5].isin(ids)].sum(), tract[tract.index.str[:5].isin(ids)].sum()])
    base = rates(pd.DataFrame({"NYC": whole(COUNTIES), "Manhattan": whole(("36061",))}).T)
    report(df, base, radius)

    k = cx.index.get_loc(TARGET)
    export_community(df, base, counts.set_axis(cx.index), fac, k, blocks, b_owner, b_dist, b_next, nyc_pop)
    mine = fac[(fac.owner == k) & np.logical_or.reduce([t(fac) for t in FAC_KINDS.values()])].sort_values("dist")
    print("Facilities nearest to 3 Av:")
    for r in mine.itertuples():
        seats = f", {r.capacity:.0f} seats" if r.capacity else ""
        print(f"  {r.dist:4.0f} m, next station {r.next:4.0f} m  {r.facname.title()} ({r.factype.title()}{seats})")


if __name__ == "__main__":
    sys.exit(main())
