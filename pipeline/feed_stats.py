"""Size up a GTFS feed before building it nationally.

Usage:
    python -I pipeline/feed_stats.py GTFS_ZIP

Prints JSON: file sizes, row counts, how many public lines the routes merge
into, and whether stop_times.txt is grouped by trip (which streaming
aggregation relies on).
"""

import json
import sys
import zipfile

sys.path.insert(0, __import__("os").path.dirname(__file__))
from build_site import line_key, read_table  # noqa: E402


def collect(gtfs_path):
    zf = zipfile.ZipFile(gtfs_path)
    files = {i.filename: {"compressed": i.compress_size, "uncompressed": i.file_size} for i in zf.infolist()}

    routes = list(read_table(zf, "routes.txt"))
    lines = {line_key(r)[0] for r in routes}
    stops = sum(1 for _ in read_table(zf, "stops.txt"))
    trips = sum(1 for _ in read_table(zf, "trips.txt"))

    rows = 0
    seen = set()
    current = None
    grouped = True
    for st in read_table(zf, "stop_times.txt"):
        rows += 1
        trip = st["trip_id"]
        if trip != current:
            if trip in seen:
                grouped = False
            seen.add(trip)
            current = trip

    return {
        "files": files,
        "routes": len(routes),
        "lines": len(lines),
        "stops": stops,
        "trips": trips,
        "stop_times_rows": rows,
        "stop_times_grouped_by_trip": grouped,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(json.dumps(collect(sys.argv[1]), indent=1))
