"""Rank stops by net rider-hours saved per weekday if cut, the same way stopthestop.com does.
Usage: python score.py [--stop-cost 50] [--walk-weight 2] [--walk-speed 1.3] [--walk line|any|station]
Writes results/ranking.csv."""
import argparse
import json

import numpy as np
import pandas as pd

from paths import RESULTS

DELTA_AT = (0, 30, 70)  # stop times (s) that timetable_cuts.py simulated
WALK = {"line": "walkLine", "any": "walkAny", "station": "walkStation"}


def ride_saved(delta, stop_cost):
    """Seconds/day of everyone else's travel time saved, interpolated between the simulated stop times."""
    i = 0 if stop_cost <= DELTA_AT[1] else 1
    slope = (delta[i + 1] - delta[i]) / (DELTA_AT[i + 1] - DELTA_AT[i])
    return -(delta[i] + slope * (stop_cost - DELTA_AT[i]))


def score(stops, stop_cost=50, walk_weight=2.0, walk_speed=1.3, walk="line"):
    d = pd.DataFrame(stops)
    d["ride_saved_hrs"] = d.rideDelta.map(lambda x: ride_saved(x, stop_cost)) / 3600
    d["walk_added_hrs"] = d.users * d[WALK[walk]] / walk_speed * walk_weight / 3600
    d["net_hrs"] = d.ride_saved_hrs - d.walk_added_hrs
    d = d.sort_values("net_hrs", ascending=False).reset_index(drop=True)
    d.insert(0, "rank", np.arange(1, len(d) + 1))
    return d.drop(columns="rideDelta").rename(columns={"id": "stop"})


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stop-cost", type=float, default=50)
    p.add_argument("--walk-weight", type=float, default=2.0)
    p.add_argument("--walk-speed", type=float, default=1.3)
    p.add_argument("--walk", choices=WALK, default="line")
    a = p.parse_args()
    stops = json.load(open(RESULTS / "stops.json"))["stops"]
    d = score(stops, a.stop_cost, a.walk_weight, a.walk_speed, a.walk)
    d.round(1).to_csv(RESULTS / "ranking.csv", index=False)
    cols = ["rank", "name", "routes", "users", "through", "ride_saved_hrs", "walk_added_hrs", "net_hrs"]
    with pd.option_context("display.width", 200, "display.float_format", "{:,.0f}".format):
        print(d[cols].head(20).to_string(index=False))
    print(f"\n{(d.net_hrs > 0).sum()} of {len(d)} stops save time if cut at these settings")


if __name__ == "__main__":
    main()
