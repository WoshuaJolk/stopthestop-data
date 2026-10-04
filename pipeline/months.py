"""Rank stops across every downloaded month and all settings. Usage: python months.py [year]"""
import glob
import os
import sys

import pandas as pd

from analyze import TAGS, load_network, run_month
from paths import OD, RESULTS

ADA = {0: "no", 1: "yes", 2: "partial"}


def main():
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    months = sorted({int(os.path.basename(f).split("-")[1]) for f in glob.glob(f"{OD}/{year}-*-h*.csv")})
    months = [m for m in months if len(glob.glob(f"{OD}/{year}-{m:02d}-h*.csv")) == 24]
    net = load_network()
    ranks, nets, waits, walks, users, through, info = [], [], [], [], [], [], None
    for m in months:
        _, elig = run_month(net, year, m)
        elig = elig.set_index("stop")
        users.append(elig.users)
        through.append(elig.through)
        info = elig[["name", "routes", "users", "through", "walk_m", "any_m", "station_m", "point_m", "line_m", "entrances", "walk_to", "ada", "walk_to_ada"]]
        for t in TAGS:
            ranks.append(elig[f"rank_{t}"].rename(f"{m:02d}_{t}"))
            nets.append(elig[f"net_{t}"].rename(f"{m:02d}_{t}"))
            waits.append(elig[f"wait_{t}"])
            walks.append(elig[f"walk_{t}"])
    ranks, nets = pd.concat(ranks, axis=1), pd.concat(nets, axis=1)
    out = info.copy()
    out["users"] = pd.concat(users, axis=1).mean(axis=1)
    out["through"] = pd.concat(through, axis=1).mean(axis=1)
    out["best_rank"] = ranks.min(axis=1)
    out["median_rank"] = ranks.median(axis=1)
    out["worst_rank"] = ranks.max(axis=1)
    out["net_min"] = nets.min(axis=1)
    out["net_median"] = nets.median(axis=1)
    out["net_max"] = nets.max(axis=1)
    waits, walks = pd.concat(waits, axis=1), pd.concat(walks, axis=1)
    out["wait_saved_min"], out["wait_saved_max"] = waits.min(axis=1), waits.max(axis=1)
    out["walk_added_min"], out["walk_added_max"] = walks.min(axis=1), walks.max(axis=1)
    out["ada"] = out.ada.map(ADA)
    out["walk_to_ada"] = out.walk_to_ada.map(ADA)
    out = out.sort_values(["worst_rank", "median_rank"])
    out.to_csv(RESULTS / f"multi_month_{year}.csv")

    print(f"\n{len(months)} months ({', '.join(map(str, months))}) x {len(TAGS)} settings = {ranks.shape[1]} rankings of {len(out)} stops")
    out["wait_saved"] = out.wait_saved_min.map("{:,.0f}".format) + "-" + out.wait_saved_max.map("{:,.0f}".format)
    out["walk_added"] = out.walk_added_min.map("{:,.0f}".format) + "-" + out.walk_added_max.map("{:,.0f}".format)
    cols = ["name", "routes", "worst_rank", "net_min", "net_median", "wait_saved", "walk_added", "station_m", "walk_m", "ada", "walk_to_ada"]
    with pd.option_context("display.width", 250, "display.float_format", "{:,.0f}".format):
        print(out[out.worst_rank <= 25][cols].to_string())


if __name__ == "__main__":
    main()
