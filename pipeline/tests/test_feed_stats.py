import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import build_site  # noqa: E402
import feed_stats  # noqa: E402
from test_build import FILES, TODAY  # noqa: E402


def make_zip(tmp_path, files=FILES):
    path = tmp_path / "g.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return str(path)


def test_counts_and_trip_grouping(tmp_path):
    stats = feed_stats.collect(make_zip(tmp_path))
    assert stats["routes"] == 4
    assert stats["lines"] == 2          # 10018 (3 variants/directions) and 10009
    assert stats["stops"] == 4
    assert stats["trips"] == 8
    assert stats["stop_times_rows"] == 20
    assert stats["stop_times_grouped_by_trip"] is True
    assert stats["files"]["stop_times.txt"]["uncompressed"] > 0


def test_detects_ungrouped_stop_times(tmp_path):
    files = dict(FILES)
    files["stop_times.txt"] += "t1,07:40:00,07:40:00,3,4\n"  # t1 appears again later
    stats = feed_stats.collect(make_zip(tmp_path, files))
    assert stats["stop_times_grouped_by_trip"] is False


def test_star_builds_every_city(tmp_path):
    cfg = build_site.config()
    cfg.update(cities=["*"], today=TODAY, manifest="", now=cfg["now"])
    stats = build_site.build(make_zip(tmp_path), str(tmp_path / "site"), cfg)
    assert stats["lines"] == 2          # includes the Haifa-only line 9
    assert os.path.exists(tmp_path / "site" / "stops" / "41004.html")
