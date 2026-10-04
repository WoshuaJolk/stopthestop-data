# Methodology

The question for each stop: if trains stopped serving it, would riders as a whole spend more or less time getting
around on an average weekday?

Two groups are affected. Riders passing through on a train get there sooner, because the train no longer stops.
Riders who started or ended a trip at the stop now walk to a neighboring station. The net is

```
net hours saved = (time saved by everyone else on trains) - (extra walking by the stop's own riders x walking penalty)
```

Everything below is how those two terms are measured.

## Pipeline

| Step | Script | Output |
| --- | --- | --- |
| 1. Download sources | `download.py`, `fetch_od.py` | `data/` |
| 2. Walking distances | `walk_dist.py`, `walk_entrances.py`, `catchment.py` | `results/walk_*.csv` |
| 3. Ridership and screening | `months.py`, `analyze.py` | `results/multi_month_2026.csv`, `results/all_stops_2026-05.csv` |
| 4. Timetable simulation | `timetable_cuts.py` (uses `raptor.py`) | `results/timetable_cuts.csv` |
| 5. Site inputs and ranking | `export.py`, `score.py` | `results/stops.json`, `results/ranking.csv` |
| 6. 3 Av deep dive | `essay_*.py` | `results/third_ave/` |

## 1. Ridership

The [MTA Subway Origin-Destination Ridership Estimate](https://data.ny.gov/d/28vm-gjqr) gives the estimated average
number of riders between every pair of station complexes, by month, day of week, and hour. It is the MTA's estimate
built from fare taps, inferring where riders exit.

`fetch_od.py` pulls January to August 2026 twice: once summed over all days of the week (divided by 7 for an average
day, used in screening), and once over Monday to Friday only (divided by 5 and by the number of months, for an
average weekday, used in the timetable simulation). The weekday average is about **4.05 million trips**. Trips that
start and end at the same complex are dropped.

## 2. Which stops are tested

A "stop" is one GTFS parent station, such as the L platform at 3 Av. Two kinds are excluded:

- **Hubs**: any stop in a complex with more than one platform group (Union Sq, Times Sq, Atlantic Av, and so on).
  Closing part of a transfer complex is a different question from closing a stop.
- **Terminals**: the first or last stop of any service pattern.

That leaves **356 stops** tested and 119 excluded (listed under `excluded` in `results/stops.json`).

## 3. Time saved on trains: the timetable simulation

`timetable_cuts.py` is the core of the analysis.

**Routing.** `raptor.py` implements [RAPTOR](https://www.microsoft.com/en-us/research/publication/round-based-public-transit-routing/),
a standard transit routing algorithm, over the MTA's weekday GTFS timetable. For each origin complex it finds the
earliest arrival at every other complex using only trains that actually run, allowing up to 3 transfers. Travel
time counts from the moment the rider arrives at the origin platform, so it includes waiting for the first train and
waiting at transfers. Transfer walking times come from the GTFS `transfers.txt`, falling back to 180 s within the
same station and 300 s between stations of a complex. Departures are sampled six times an hour (:05, :15, ... :55),
and each hour's travel time is the mean over those samples. Service after midnight is also run at the start of the
day. The Staten Island Railway is excluded.

**Removing a stop.** The stop is deleted from every trip that serves it (except where it is the trip's first or
last stop). The timetable is not shifted. Instead, each trip carries a running total of time saved, so a rider who
boards before the skipped stop arrives `stop_cost` seconds earlier for each stop skipped, while a rider boarding
after it sees the same departure times as today. Shifting the whole timetable would move trains relative to the
sampled departure times and create large, spurious changes in waiting time.

**Totaling.** For every hour and every origin-destination pair that does not start or end at the removed stop:

```
change = sum over hours, origins, destinations of riders x (travel time without stop - travel time today)
```

This captures more than "seconds saved per passing rider." Riders can make a connection they used to miss (the
Bedford Av to Grand Central example on the site), and riders who used to transfer at the stop can lose time.

**Stop cost.** How long a stop costs a passing train (braking, dwell, accelerating) is not published by the MTA,
and the GTFS schedule does not separate it from running time. The simulation is run at stop costs of 0, 30, and
70 seconds (`d0_s`, `d30_s`, `d70_s`), and other values are linearly interpolated between them. The site default is
**50 seconds**. At 0 seconds the only effect is lost transfers.

`through_eff` is the change in total travel time per extra second of stop cost, between 30 and 70 s. It reads as
"riders effectively passing through," and is what the site shows as "riders passing through."

## 4. Extra walking for the stop's own riders

`users` is the number of weekday trips that start or end at the stop's complex.

Each of those riders is assumed to walk to another station instead. Three distances are computed, and the site lets
you pick:

- **Next stop on the same line** (`walkLine`, the default). `catchment.py` builds the walking network from
  OpenStreetMap and finds every street node whose nearest station entrance (within 1,200 m on foot) belongs to the
  stop. For each node, the extra distance is the walk to the nearest entrance of another station that shares a
  route, minus the walk to the stop's own nearest entrance (capped at 3,000 m). Nodes are weighted by the 2020 Census residents and the
  LODES 2022 jobs nearest to them, and averaged.
- **Nearest station, any line** (`walkAny`). The same, but the other station can serve any route.
- **Station to station** (`walkStation`). The street walk from each of the stop's entrances to the nearest entrance
  of an adjacent station, averaged over entrances, from the public Valhalla routing server. This is a worst case: it
  assumes every rider starts at the closed station itself.

Walking time is `distance / walking speed` (default **1.3 m/s**, about 4.7 km/h). Because walking is less pleasant
than riding, it is multiplied by a **walking penalty** (default **2x**: a minute of walking counts as two minutes on
a train).

## 5. Score

```
ride saved (s/day)   = -interpolate(d0_s, d30_s, d70_s at stop_cost)
walk added (s/day)   = users x walk distance / walking speed x walking penalty
net hours saved/day  = (ride saved - walk added) / 3600
```

`score.py` computes this for any settings. It is a line-for-line port of the site's scoring code.

## Robustness

The ranking leans most on two assumptions, the stop cost and the walking penalty. You can sweep them with
`score.py`. The site's sensitivity grid covers stop costs of 20 to 90 seconds and penalties of 1x to 3x.

`months.py` is an earlier, simpler screening model kept for transparency: it assigns trips on a static network (median
run times, no waiting) and computes `through x stop_cost - users x walk / speed x penalty` for each month from January
to August and four settings (stop cost 45 or 60 s, penalty 1x or 2x). Its `best_rank`, `median_rank`, and
`worst_rank` columns show how stable a stop's position is across months. It is also where the ridership and walking
inputs are joined, and it defines which stops the timetable simulation tests.

## The 3 Av deep dive

The essay's figures for 3 Av use the same models, run once for that stop at a 50 s stop cost:

- `essay_trips.py` reruns the timetable simulation with and without 3 Av and keeps the per-trip detail: how many
  trips change, by how much, which stations gain the most (half of each trip's saving is credited to each end), and
  morning trips from Brooklyn L stations that save 4 minutes or more by making an earlier connection.
- `essay_walkshed.py` exports the street points behind 3 Av's `walkLine` value.
- `essay_ridership.py` counts entries plus exits per complex at morning rush from the weekday ridership data, and
  L riders getting on, off, and riding through each 14th St stop from 5 to 6pm. The latter routes trips on the
  screening model's static network, not the timetable. Union Sq counts all lines in its complex.
- `essay_grid.py` sweeps stop cost and walking penalty for 3 Av.

## What the model leaves out

These are known simplifications. Some favor cutting a stop, some favor keeping it.

- **New riders.** Faster trips attract riders. Not counted.
- **Lost riders.** Some of a closed stop's riders would switch to buses or stop riding rather than walk. They are
  counted as walking.
- **Crowding and reliability.** Fewer stops can mean shorter headways or more reliable service. Not modeled. Dwell
  time is the same at every stop and every hour.
- **Weekends.** Weekday schedule and ridership only.
- **Operations.** No change to the schedule beyond skipping the stop: no recovered train-hours, no added service.
- **Accessibility.** Whether the stop and its neighbors are wheelchair accessible is reported (`ada`,
  `walk_to_ada`) but not part of the score.
- **Schedule mismatch.** Ridership is January to August 2026. The pinned GTFS is the schedule in effect from May 26
  to October 31, 2026.
- **Unreachable trips.** A handful of trips cannot be routed in the timetable (about 2,800 a day).
  They are dropped from both scenarios.
