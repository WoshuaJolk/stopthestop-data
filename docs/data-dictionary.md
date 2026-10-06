# Data dictionary

Units: trips and riders are per average day; times are seconds unless a column says `hrs`; distances are meters.
`stop` is the GTFS parent stop ID (for example `L05` is 3 Av on the L), and `complex` is the MTA station complex ID.

## ranking.csv

One row per tested stop, ranked at the settings passed to `score.py` (defaults: 50 s stop cost, 2x walking penalty,
1.3 m/s, walk to the next stop on the same line).

| Column | Meaning |
| --- | --- |
| `rank` | 1 = most net time saved if cut |
| `users` | Weekday trips starting or ending at the stop |
| `through` | Riders effectively passing through (`through_eff` below) |
| `walkLine`, `walkAny`, `walkStation` | Extra walk per user if the stop closes, under each walking assumption ([methodology](methodology.md#4-extra-walking-for-the-stops-own-riders)) |
| `ada` | Wheelchair accessible: `yes`, `partial`, or `no` |
| `ride_saved_hrs` | Rider-hours per weekday saved by everyone else on trains |
| `walk_added_hrs` | Rider-hours per weekday of extra walking, after the walking penalty |
| `net_hrs` | `ride_saved_hrs - walk_added_hrs`; positive means cutting the stop saves time |

## stops.json

What the site loads. `stops` has one entry per tested stop with `users`, `through`, `walkLine`, `walkAny`,
`walkStation`, `ada` as above, and `rideDelta`: `[d0_s, d30_s, d70_s]` from `timetable_cuts.csv`, rounded.
`excluded` lists the stops not tested, with `reason` `hub` or `terminal`.

## timetable_cuts.csv

Output of the timetable simulation, average weekday.

| Column | Meaning |
| --- | --- |
| `users` | Weekday trips starting or ending at the stop's complex |
| `through_eff` | Rider-seconds saved per extra second of stop cost, between 30 and 70 s; reads as riders passing through |
| `unreachable` | Trips that could not be routed once the stop was removed (dropped from the total) |
| `d0_s`, `d30_s`, `d70_s` | Change in total travel time of all other weekday trips, in rider-seconds per day, with the stop removed and a stop cost of 0, 30, or 70 s. Negative = faster |

## multi_month_2026.csv

Screening model across January to August 2026 (all days of the week). Defines which stops are tested.

| Column | Meaning |
| --- | --- |
| `users`, `through` | Mean daily trips starting/ending at, and riding through, the stop on a static network |
| `walk_m` | Population- and job-weighted extra walk to the next stop on the same line (`walkLine`) |
| `any_m` | Same, to the nearest station on any line (`walkAny`) |
| `station_m` | Mean walk from the stop's entrances to the nearest entrance of an adjacent station (`walkStation`) |
| `point_m` | Street walk between station center points |
| `line_m` | Straight-line distance to the neighbor in `walk_to` |
| `entrances` | Whether entrance locations were available for the stop |
| `walk_to`, `walk_to_ada` | The neighboring station riders would walk to, and its accessibility |
| `best_rank`, `median_rank`, `worst_rank` | Rank across 8 months x 4 settings (stop cost 45/60 s, penalty 1x/2x) |
| `net_min`, `net_median`, `net_max` | Net rider-hours per day across those 32 runs |
| `wait_saved_*`, `walk_added_*` | Range of the two terms, rider-hours per day |

## all_stops_2026-05.csv, ranked_2026-05.csv

The screening model for May 2026 alone. `all_stops` includes every stop; `ranked` only the tested ones, with a rank
per setting. Columns match `multi_month_2026.csv`, plus `complex`, `transfers` (riders transferring there), `street`
(whether a street walk was found), `hub`, `terminal`, and `wait_`, `walk_`, `net_`, `rank_` per setting
`sp{stop cost}_ww{walking penalty}`. `ada` here is coded `0` no, `1` yes, `2` partial.

## walk_catchment.csv

| Column | Meaning |
| --- | --- |
| `catchment_pop`, `catchment_jobs` | Residents and jobs whose nearest station entrance (within 1,200 m on foot) belongs to the stop |
| `added_line_m`, `added_any_m` | Weighted mean extra walk to the next station on the same line, or on any line |

## demographics.csv

One row per station complex (`Complex ID`, `name`, `routes`, `borough`, `ada`): who lives nearest it, who rides
from it, and what is nearby ([methodology](methodology.md#who-lives-near-each-station)). Shares are percentages.

| Column | Meaning |
| --- | --- |
| `residents` | 2020 residents whose nearest complex this is |
| `pct_65plus`, `pct_75plus`, `pct_under18`, `pct_under5`, `pct_18_24` | Share of residents by age |
| `pct_college` | Share of residents enrolled in college or graduate school |
| `pct_65_alone_hh` | Share of households that are one person aged 65 or older |
| `pct_disabled`, `pct_disabled_65plus`, `pct_walking_difficulty` | Share with a disability, among everyone and among those 65 and older, and share with serious difficulty walking or climbing stairs |
| `pct_poverty`, `pct_under_2x_poverty`, `pct_hh_under_25k` | Share below the poverty line, below twice it, and households earning under $25k |
| `median_hh_income_k` | Median household income, $ thousands, from pooled income bins; top-coded at 200 |
| `pct_people_of_color`, `pct_black`, `pct_hispanic`, `pct_asian`, `pct_white` | Share by race and Hispanic origin; people of color is everyone except non-Hispanic white alone |
| `pct_limited_english`, `pct_foreign_born`, `pct_hh_no_car` | Share aged 5+ speaking English less than very well, share born abroad, and households with no vehicle |
| `n_65plus`, `n_under18`, `n_disabled`, `n_walking_difficulty`, `n_poverty`, `n_65_alone_hh` | The same groups as headcounts |
| `schools_k12`, `special_ed_schools`, `daycare_prek`, `hospitals`, `hospital_clinics`, `nursing_homes`, `senior_centers`, `disability_programs` | Facilities whose nearest complex this is |
| `public_school_seats` | Seats in the public K-12 schools among them |
| `entries_per_day` | Entries per day, January to August 2026 |
| `ride_pct_senior_disability`, `ride_pct_fair_fares`, `ride_pct_student` | Share of entries paid with a senior or disability fare, Fair Fares, or a student pass |
| `ride_*_per_day` | The same, as entries per day |
| `r500_*` | The resident measures above for everyone within a 500 m walk, whether or not this is their nearest complex |

## community.json

The numbers on the site's community page. `residents`, `counts`, and `riders` give, per measure, the value at 3 Av
(`av3`), Union Sq, and 1 Av, the median across complexes (`median`) and across L complexes (`lMedian`), the
Manhattan and citywide rate where one applies, and 3 Av's `rank` out of `of` complexes (1 = highest). `distance` is
the mean walk to a station for 3 Av's residents today (`now`) and if it closed (`after`), and how many New Yorkers
already live farther than that. `places` lists the schools and hospitals nearest 3 Av with the walk to it and to
the next station. `line` pools the residents nearest the other 23 L complexes.

## walk_entrance.csv, walk_street.csv

`walk_entrance.csv`: for each entrance (`lat`, `lon`) of `stop`, the street walk in `meters` to the nearest entrance
of an adjacent station, `to_stop`. `walk_street.csv`: street walk between the center points of adjacent stops
`from` and `to`.
