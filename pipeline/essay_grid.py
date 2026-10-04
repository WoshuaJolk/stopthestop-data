"""3 Av's net hours saved across stop costs and walking penalties (Exhibit H), and how many stops save time at the
site's defaults. Reads results/stops.json."""
import json

from paths import RESULTS
from score import score

STOP = "L05"
STOP_COSTS = range(20, 100, 10)
WALK_WEIGHTS = (1, 1.5, 2, 2.5, 3)


def main():
    stops = json.load(open(RESULTS / "stops.json"))["stops"]
    d = score(stops)
    print(f"at defaults: {(d.net_hrs > 0).sum()} of {len(d)} stops save time; "
          f"worst is {d.name.iloc[-1]} ({d.routes.iloc[-1]}) at {d.net_hrs.iloc[-1]:,.0f} h/day\n")
    grid = {ww: [score(stops, sp, ww).set_index("stop").net_hrs[STOP] for sp in STOP_COSTS] for ww in WALK_WEIGHTS}
    print("walk penalty \\ stop cost " + "".join(f"{sp:>7}s" for sp in STOP_COSTS))
    for ww, row in grid.items():
        print(f"{ww:>24}x" + "".join(f"{v:>8,.0f}" for v in row))
    cells = [v for row in grid.values() for v in row]
    print(f"\n3 Av saves time in {sum(v > 0 for v in cells)} of {len(cells)} combinations")


if __name__ == "__main__":
    main()
