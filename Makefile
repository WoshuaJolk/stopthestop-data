PY ?= python
MONTHS := 1 2 3 4 5 6 7 8

.PHONY: score results rank export third-ave download od walks timetable all

# Fast: rank stops from the committed results (seconds)
score:
	$(PY) pipeline/score.py

# Rebuild results/ from the committed walk distances and timetable runs (needs data/od, about a minute)
results: rank export

rank:
	$(PY) pipeline/months.py 2026
	$(PY) pipeline/analyze.py 2026 5

export:
	$(PY) pipeline/export.py
	$(PY) pipeline/score.py

# The 3rd Ave figures in the essay (needs data/: run make download and make od first; a few minutes)
third-ave:
	$(PY) pipeline/essay_walkshed.py
	$(PY) pipeline/essay_trips.py
	$(PY) pipeline/essay_ridership.py
	$(PY) pipeline/essay_grid.py

download:
	$(PY) pipeline/download.py

# MTA origin-destination ridership, Jan-Aug 2026 (slow: hundreds of API pages)
od:
	for m in $(MONTHS); do $(PY) pipeline/fetch_od.py 2026 $$m && $(PY) pipeline/fetch_od.py 2026 $$m --weekday; done

# Walking distances (public Valhalla server, about an hour each) and the population-weighted walkshed
walks:
	rm -f results/walk_street.csv results/walk_entrance.csv
	$(PY) pipeline/walk_dist.py
	$(PY) pipeline/walk_entrances.py
	$(PY) pipeline/catchment.py

# The full timetable simulation: every eligible stop at three stop times (hours, uses all cores)
timetable:
	rm -f results/timetable_cuts.csv
	$(PY) pipeline/timetable_cuts.py

all: download od walks rank timetable export third-ave
