"""Write results/stops.json: the per-stop inputs the website scores live (see score.py)."""
import json

import pandas as pd

from paths import RESULTS

d = pd.read_csv(RESULTS / "multi_month_2026.csv", dtype={"stop": str})
tt = pd.read_csv(RESULTS / "timetable_cuts.csv", dtype={"stop": str}).set_index("stop")
d = d[d.stop.isin(tt.index)]
stops = [dict(id=r.stop, name=r["name"], routes=r.routes, users=round(tt.at[r.stop, "users"]),
              through=round(tt.at[r.stop, "through_eff"]),
              walkLine=round(r.walk_m), walkAny=round(r.any_m) if pd.notna(r.any_m) else round(r.walk_m),
              walkStation=round(r.station_m), ada=r.ada,
              # change in everyone else's weekday travel time, seconds/day, at stop times 0, 30, 70 s
              rideDelta=[round(tt.at[r.stop, c]) for c in ("d0_s", "d30_s", "d70_s")])
         for _, r in d.iterrows()]
a = pd.read_csv(RESULTS / "all_stops_2026-05.csv", dtype={"stop": str})
a = a[~a.stop.isin(d.stop)]
excluded = [dict(id=r.stop, name=r["name"], routes=r.routes, reason="hub" if r.hub else "terminal")
            for _, r in a.sort_values(["name", "stop"]).iterrows()]
json.dump(dict(stops=stops, excluded=excluded), open(RESULTS / "stops.json", "w"), indent=1)
print(len(stops), len(excluded))
