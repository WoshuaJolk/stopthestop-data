"""Download the large public inputs into data/. Usage: python download.py [--refresh-inputs]

--refresh-inputs also replaces the pinned GTFS, station, and entrance files in inputs/ with today's versions,
which will change the results."""
import sys
import zipfile

import requests

from paths import BLOCKS, DATA, ENTRANCES, GTFS, OSM, STATIONS, WAC

LARGE = {
    OSM: "https://download.bbbike.org/osm/bbbike/NewYork/NewYork.osm.pbf",
    WAC: "https://lehd.ces.census.gov/data/lodes/LODES8/ny/wac/ny_wac_S000_JT00_2022.csv.gz",
}
BLOCKS_ZIP = "https://www2.census.gov/geo/tiger/TIGER2020/TABBLOCK20/tl_2020_36_tabblock20.zip"
PINNED = {
    GTFS: "http://web.mta.info/developers/data/nyct/subway/google_transit.zip",
    STATIONS: "https://data.ny.gov/api/views/39hk-dx4f/rows.csv?accessType=DOWNLOAD",
    ENTRANCES: "https://data.ny.gov/api/views/i9wp-a4ja/rows.csv?accessType=DOWNLOAD",
}


def fetch(url, out):
    print(f"{url} -> {out.relative_to(DATA.parent)}", flush=True)
    tmp = out.with_suffix(out.suffix + ".part")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    tmp.replace(out)


def main():
    DATA.mkdir(exist_ok=True)
    for out, url in LARGE.items():
        if not out.exists():
            fetch(url, out)
    if not BLOCKS.exists():
        zip_path = DATA / "tl_2020_36_tabblock20.zip"
        if not zip_path.exists():
            fetch(BLOCKS_ZIP, zip_path)
        with zipfile.ZipFile(zip_path) as z:
            z.extract(BLOCKS.name, DATA)
        zip_path.unlink()
    if "--refresh-inputs" in sys.argv:
        for out, url in PINNED.items():
            fetch(url, out)


if __name__ == "__main__":
    main()
