"""Repository paths, so every script runs from any working directory."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUTS = ROOT / "inputs"  # small source files pinned in the repo
DATA = ROOT / "data"  # large downloads, not committed
RESULTS = ROOT / "results"  # pipeline outputs, committed

GTFS = INPUTS / "gtfs_subway.zip"
STATIONS = INPUTS / "stations.csv"
ENTRANCES = INPUTS / "entrances.csv"
OD = DATA / "od"
OD_WEEKDAY = DATA / "od_wkday"
OSM = DATA / "nyc.osm.pbf"
BLOCKS = DATA / "tl_2020_36_tabblock20.dbf"
WAC = DATA / "ny_wac.csv.gz"
