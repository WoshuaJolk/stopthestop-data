# Stop the Stop

![Check results](../../actions/workflows/check.yml/badge.svg)

Data and code behind [stopthestop.com](https://stopthestop.com): for every NYC subway stop, how many rider-hours a
weekday would be saved, or lost, if trains stopped serving it.

Every weekday subway trip (about 4.05 million, from the MTA's origin-destination estimates for January to August
2026) is routed through the real weekday timetable. Then one stop is deleted, everything is routed again, and the
time saved by riders passing through is weighed against the extra walk for the riders who used it. This is repeated
for each of the 356 stops that are not transfer hubs or terminals.

At the default settings, 3 Av on the L comes out first, saving about 1,800 net rider-hours per weekday. 298 of the
356 stops would cost riders time if cut.

## Just want the numbers?

Everything the site shows is in [`results/`](results). No setup needed.

| File | What it is |
| --- | --- |
| [`ranking.csv`](results/ranking.csv) | Every stop ranked by net hours saved per weekday, at the site's default settings |
| [`stops.json`](results/stops.json) | The per-stop inputs the site uses to recompute the ranking live as you move its sliders |
| [`timetable_cuts.csv`](results/timetable_cuts.csv) | The core simulation: change in everyone else's weekday travel time when each stop is removed |
| [`multi_month_2026.csv`](results/multi_month_2026.csv) | Ridership counts and walking distances per stop, plus a simpler screening ranking across 8 months x 4 settings |
| [`walk_catchment.csv`](results/walk_catchment.csv) | Population- and job-weighted extra walk if a stop closes |
| [`walk_entrance.csv`](results/walk_entrance.csv), [`walk_street.csv`](results/walk_street.csv) | Street walking distances between neighboring stations |
| [`all_stops_2026-05.csv`](results/all_stops_2026-05.csv), [`ranked_2026-05.csv`](results/ranked_2026-05.csv) | Screening model for May 2026 alone, including excluded hubs and terminals |
| [`demographics.csv`](results/demographics.csv) | Who lives nearest each station complex (age, disability, income, race, language), who rides from it by fare class, and the schools and hospitals closest to it |
| [`community.json`](results/community.json) | The numbers on the site's [community page](https://stopthestop.com/community): 3 Av against its neighbors, the typical station, the rest of the L, and the city |

The numbers in the site's essay about 3 Av are in [`results/third_ave/`](results/third_ave):

| File | What it is |
| --- | --- |
| [`trip_changes.json`](results/third_ave/trip_changes.json) | Per-trip change in travel time if 3 Av closes, hours saved by station, and example trips (Exhibits C, D, G; "195,000 trips", "25,000 save more than a minute") |
| [`walkshed.json`](results/third_ave/walkshed.json) | Every street point in 3 Av's walkshed with its residents plus jobs and extra walk (Exhibit F) |
| [`ridership.json`](results/third_ave/ridership.json) | Morning rush entries and exits ("5x and 17x") and L riders on, off, and through at 5pm (Exhibit B) |

`python pipeline/essay_grid.py` prints the stop cost by walking penalty grid (Exhibit H, "39 of 40").

Column definitions are in [`docs/data-dictionary.md`](docs/data-dictionary.md). How each number is computed, and what
the model leaves out, is in [`docs/methodology.md`](docs/methodology.md).

## Rerun it

Requires Python 3.12+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

There are three levels, from seconds to a day of compute.

**1. Re-rank with your own assumptions** (seconds, no downloads). Change how long a stop takes, how much worse
walking feels than riding, walking speed, or where riders walk to:

```bash
python pipeline/score.py --stop-cost 30 --walk-weight 3 --walk-speed 1.1 --walk any
```

This is the same calculation as the site's sliders, and writes `results/ranking.csv`.

**2. Rebuild the rankings from ridership** (about an hour to download, a minute to run). Pulls the MTA's
origin-destination data and recomputes everything except the walking distances and the timetable simulation, which
are reused from `results/`:

```bash
make od        # MTA ridership, Jan-Aug 2026, into data/
make results
```

**3. Reproduce everything from scratch.** Also downloads OpenStreetMap, Census blocks, and Census job counts (about
500 MB), recomputes walking distances against a public routing server, and reruns the timetable simulation for
every stop. The simulation takes several hours on a laptop and uses every core.

```bash
make all
```

`make third-ave` regenerates the 3 Av figures once `data/` is downloaded, and `make community` the demographics (it
also fetches Census, fare, and facility data into `data/demo`). `make -n all` prints each step without running it.

## Data sources

| Source | Used for | Where |
| --- | --- | --- |
| [MTA Subway Origin-Destination Ridership Estimate](https://data.ny.gov/d/28vm-gjqr) | Trips between every pair of stations, by hour | Downloaded to `data/od*/` |
| [MTA subway GTFS](https://new.mta.info/developers) | Weekday timetable, transfer times | `inputs/gtfs_subway.zip` (feed version 20260826) |
| [MTA Subway Stations](https://data.ny.gov/d/39hk-dx4f) | Station complexes, coordinates, accessibility | `inputs/stations.csv` |
| [MTA Subway Entrances and Exits](https://data.ny.gov/d/i9wp-a4ja) | Entrance locations | `inputs/entrances.csv` |
| [OpenStreetMap](https://www.openstreetmap.org) via [BBBike](https://download.bbbike.org/osm/bbbike/NewYork/) | Walking network | Downloaded to `data/` |
| [2020 Census blocks](https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html) | Residents near each station | Downloaded to `data/` |
| [Census LEHD LODES 8](https://lehd.ces.census.gov/data/) (2022 WAC) | Jobs near each station | Downloaded to `data/` |
| [Valhalla](https://github.com/valhalla/valhalla) public server (FOSSGIS) | Street walking distances | Queried by `walk_dist.py`, `walk_entrances.py` |

The GTFS, station, and entrance files are pinned in `inputs/` because the MTA replaces them as schedules change, and
a newer timetable gives different results. `python pipeline/download.py --refresh-inputs` swaps in today's versions.

## Layout

```
inputs/     small source files pinned at the versions used
pipeline/   the analysis, one script per step (see docs/methodology.md for the order)
results/    every output, committed
data/       large downloads, not committed (created by make)
docs/       methodology and column definitions
```

## Credits

Routing inspired by Anita's [NYC Subway Riders](https://anita.garden/nycriders/). Code is MIT licensed. Data
belongs to its sources above and is used under their terms; OpenStreetMap data is © OpenStreetMap contributors (ODbL).

Questions or a bug in the numbers? Open an issue.
