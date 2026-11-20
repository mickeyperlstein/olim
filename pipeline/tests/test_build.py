import json
import os
import re
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import build_site  # noqa: E402

LINE = "10018-3"
TODAY = __import__("datetime").date(2026, 11, 20)
_dt = __import__("datetime")
NOW = _dt.datetime(2026, 11, 20, 0, 47, tzinfo=_dt.timezone(_dt.timedelta(hours=2)))

FILES = {
    "agency.txt": "agency_id,agency_name,agency_url\n3,אגד,http://egged.co.il\n",
    "stops.txt": (
        "stop_id,stop_code,stop_name,stop_desc,stop_lat,stop_lon\n"
        "1,21001,צומת קרית אונו,רחוב: לוי אשכול עיר: קרית אונו רציף:  קומה: ,32.06,34.85\n"
        "2,21002,לוי אשכול/הרצל,רחוב: לוי אשכול עיר: קרית אונו רציף:  קומה: ,32.06,34.86\n"
        "3,31003,תחנה מרכזית,רחוב: לוינסקי עיר: תל אביב יפו רציף: 7 קומה: 6,32.05,34.78\n"
        "4,41004,רחוק,רחוב: כלשהו עיר: חיפה רציף:  קומה: ,32.8,35.0\n"
    ),
    "routes.txt": (
        "route_id,agency_id,route_short_name,route_long_name,route_desc,route_type\n"
        "100,3,18,צומת קרית אונו-קרית אונו<->תחנה מרכזית-תל אביב יפו-1#,10018-1-0,3\n"
        "101,3,18,צומת קרית אונו-קרית אונו<->תחנה מרכזית-תל אביב יפו-1#,10018-1-1,3\n"
        "102,3,18,תחנה מרכזית-תל אביב יפו<->צומת קרית אונו-קרית אונו-2#,10018-2-0,3\n"
        "200,3,9,רחוק-חיפה<->רחוק-חיפה-1#,10009-1-#,3\n"
    ),
    "calendar.txt": (
        "service_id,sunday,monday,tuesday,wednesday,thursday,friday,saturday,start_date,end_date\n"
        "WK,1,1,1,1,1,0,0,20261101,20261201\n"
        "FR,0,0,0,0,0,1,0,20261101,20261201\n"
        "OLD,1,1,1,1,1,1,1,20260101,20260201\n"
    ),
    "trips.txt": (
        "route_id,service_id,trip_id,trip_headsign,direction_id,shape_id\n"
        "100,WK,t1,,0,\n101,WK,t6,,0,\n102,WK,t7,,1,\n100,WK,t2,,0,\n100,WK,t3,,0,\n100,FR,t4,,0,\n200,WK,t9,,0,\n100,OLD,t5,,0,\n"
    ),
    "stop_times.txt": (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "t1,07:00:00,07:00:00,1,1\nt1,07:04:00,07:04:00,2,2\nt1,07:30:00,07:30:00,3,3\n"
        "t2,07:15:00,07:15:00,1,1\nt2,07:19:00,07:19:00,2,2\nt2,07:45:00,07:45:00,3,3\n"
        "t3,24:10:00,24:10:00,1,1\nt3,24:14:00,24:14:00,2,2\nt3,24:40:00,24:40:00,3,3\n"
        "t4,13:00:00,13:00:00,1,1\nt4,13:04:00,13:04:00,2,2\nt4,13:30:00,13:30:00,3,3\n"
        "t9,08:00:00,08:00:00,4,1\n"
        "t6,09:00:00,09:00:00,1,1\nt6,09:30:00,09:30:00,3,2\n"
        "t7,08:00:00,08:00:00,3,1\nt7,08:30:00,08:30:00,1,2\n"
        "t5,05:05:00,05:05:00,1,1\nt5,05:09:00,05:09:00,2,2\nt5,05:35:00,05:35:00,3,3\n"
    ),
}


class BuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.zip = os.path.join(cls.tmp, "gtfs.zip")
        with zipfile.ZipFile(cls.zip, "w") as zf:
            for name, text in FILES.items():
                zf.writestr(name, "﻿" + text)
        cls.out = os.path.join(cls.tmp, "site")
        cfg = build_site.config()
        cfg["cities"] = ["קרית אונו"]
        cfg["today"] = TODAY
        cfg["now"] = NOW
        cfg["manifest"] = os.path.join(cls.tmp, "pages.json")
        cls.cfg = cfg
        cls.stats = build_site.build(cls.zip, cls.out, cfg)

    def read(self, rel):
        with open(os.path.join(self.out, rel), encoding="utf-8") as f:
            return f.read()

    def test_only_city_lines(self):
        self.assertEqual(self.stats["lines"], 1)
        self.assertTrue(os.path.exists(os.path.join(self.out, f"lines/{LINE}.html")))
        self.assertEqual(sorted(os.listdir(os.path.join(self.out, "lines"))), [f"{LINE}.html"])

    def test_stops_include_whole_route(self):
        for code in ("21001", "21002", "31003"):
            self.assertTrue(os.path.exists(os.path.join(self.out, f"stops/{code}.html")), code)
        self.assertFalse(os.path.exists(os.path.join(self.out, "stops/41004.html")))

    def test_line_page_links_to_stops_and_back(self):
        line = self.read(f"lines/{LINE}.html")
        self.assertIn(f'href="../stops/21001.html?line={LINE}&amp;dir=1"', line)
        self.assertIn(f'href="../stops/31003.html?line={LINE}&amp;dir=1"', line)
        stop = self.read("stops/31003.html")
        self.assertIn(f'href="../lines/{LINE}.html#dir-1"', stop)
        self.assertIn(f'href="../lines/{LINE}.html#dir-2"', stop)

    def test_times_and_faq_come_from_data(self):
        line = self.read(f"lines/{LINE}.html")
        self.assertIn("קו 18 צומת קרית אונו (קרית אונו) – תחנה מרכזית (תל אביב יפו)", line)
        self.assertIn('id="dir-2"', line)
        self.assertIn("09:00", line)  # second variant folded into direction 1
        self.assertIn("מתי יוצא קו 18 הראשון מתחנה מרכזית (תל אביב יפו)?", line)
        self.assertIn("בימים א׳–ה׳ ב־07:00", line)
        self.assertIn("00:10", line)  # after-midnight trip shown as 00:10
        self.assertIn("ביום שישי ב־13:00", line)
        self.assertIn("הקו לא פועל בשבת", line)
        self.assertIn('"@type": "FAQPage"', line)
        self.assertIn("00:10 (אחרי חצות)", line)

    def test_expired_services_ignored(self):
        line = self.read(f"lines/{LINE}.html")
        self.assertNotIn("05:05", line)

    def test_analytics_and_cta(self):
        line = self.read(f"lines/{LINE}.html")
        self.assertIn('data-goatcounter="https://olim.goatcounter.com/count"', line)
        self.assertIn('data-goatcounter-click="notify-click"', line)

    def test_sitemap_and_robots(self):
        sitemap = self.read("sitemap.xml")
        self.assertEqual(len(re.findall("<url>", sitemap)), self.stats["pages"])
        self.assertIn("OAI-SearchBot", self.read("robots.txt"))

    def test_streetview(self):
        stop = self.read("stops/21001.html")
        self.assertIn("map_action=pano&amp;viewpoint=32.060000,34.850000", stop)
        self.assertNotIn("sv-btn", stop)  # no key, no embed
        cfg = build_site.config()
        cfg["maps_key"] = "KEY"
        block = build_site.streetview_part(cfg, {"stop_lat": "32.06", "stop_lon": "34.85"})
        self.assertIn("embed/v1/streetview?key=KEY&amp;location=32.060000,34.850000", block)
        self.assertEqual(build_site.streetview_part(cfg, {"stop_lat": "x", "stop_lon": ""}), "")

    def test_photo_link_in_stop_view(self):
        stop = self.read("stops/21001.html")
        block = stop.split("<h2>מבט על התחנה</h2>", 1)[1].split("</section>", 1)[0]
        self.assertIn('data-goatcounter-click="stop-photo"', block)
        self.assertIn("1FAIpQLSebfySl9fRH426wO5BBUStbU286SvYIcwFR7IZzy5TPPZGHnA/viewform?usp=pp_url&amp;entry.720812025=21001", block)
        self.assertIn('data-line-field="entry.570657219"', block)
        self.assertIn('data-visit-time="entry.127162871"', block)

    def test_indexnow_key_file_at_root(self):
        key = build_site.config()["indexnow_key"]
        self.assertRegex(key, r"^[0-9a-f]{32}$")
        self.assertEqual(self.read(f"{key}.txt"), key)

    def test_changed_urls_listed_for_indexnow(self):
        # first build: every page is new
        self.assertIn(f"https://olim-app.com/lines/{LINE}.html", self.stats["changed_urls"])
        self.assertNotIn("https://olim-app.com/notify.html", self.stats["changed_urls"])
        # same feed a day later: nothing to announce
        day = _dt.timedelta(days=1)
        cfg = dict(self.cfg, today=TODAY + day, now=NOW + day)
        out = os.path.join(self.tmp, "site_idx")
        build_site.build(self.zip, out, dict(cfg, manifest=self.cfg["manifest"]))  # settle
        stats = build_site.build(self.zip, out, dict(cfg, manifest=self.cfg["manifest"]))
        self.assertEqual(stats["changed_urls"], [])

    def test_bing_site_auth_file_at_root(self):
        xml = self.read("BingSiteAuth.xml")
        self.assertIn("<user>35A50FF268C7AED20040D00BAEC0E23E</user>", xml)
        self.assertTrue(xml.startswith('<?xml version="1.0"?>'))

    def test_announce_all_lists_every_page(self):
        out = os.path.join(self.tmp, "site_all")
        stats = build_site.build(self.zip, out, dict(self.cfg, announce_all=True))
        self.assertEqual(len(stats["changed_urls"]), stats["pages"])

    def test_site_lives_on_own_domain(self):
        line = self.read(f"lines/{LINE}.html")
        self.assertIn(f'<link rel="canonical" href="https://olim-app.com/lines/{LINE}.html">', line)
        self.assertIn("<loc>https://olim-app.com/index.html</loc>", self.read("sitemap.xml"))
        self.assertIn("Sitemap: https://olim-app.com/sitemap.xml", self.read("robots.txt"))
        self.assertNotIn("github.io", line)

    def test_map_link_pins_the_stop(self):
        # Street View links can't carry a map position, so backing out of them lands
        # on an empty map. The map link drops a pin on the stop instead.
        stop = self.read("stops/21001.html")
        self.assertIn(
            'href="https://www.google.com/maps/search/?api=1&amp;query=32.060000%2C34.850000"', stop
        )
        self.assertIn('data-goatcounter-click="map-link"', stop)
        # the map link comes before the Street View link
        self.assertLess(stop.index('data-goatcounter-click="map-link"'),
                        stop.index('data-goatcounter-click="streetview-link"'))

    def test_stops_are_numbered(self):
        line = self.read(f"lines/{LINE}.html")
        self.assertIn('<span class="num">1</span><a href="../stops/21001.html?', line)
        self.assertIn('<span class="num">3</span><a href="../stops/31003.html?', line)

    def test_search_box_on_every_page(self):
        for rel in ("index.html", f"lines/{LINE}.html", "stops/21001.html"):
            self.assertIn('id="find"', self.read(rel), rel)
        self.assertIn('src="../site.js"', self.read(f"lines/{LINE}.html"))
        self.assertTrue(os.path.exists(os.path.join(self.out, "site.js")))

    def test_last_updated_moves_only_on_change(self):
        self.assertIn('<time datetime="2026-11-20T00:47+02:00">עודכן לאחרונה בתאריך 20.11.2026 ובשעה 00:47</time>.', self.read("index.html"))
        self.assertIn("<lastmod>2026-11-20T00:47+02:00</lastmod>", self.read("sitemap.xml"))
        # Rebuild a day later from the same feed: nothing changed, dates stay.
        day = _dt.timedelta(days=1)
        cfg = dict(self.cfg, today=TODAY + day, now=NOW + day)
        out2 = os.path.join(self.tmp, "site2")
        stats = build_site.build(self.zip, out2, cfg)
        with open(os.path.join(out2, "stops/21001.html"), encoding="utf-8") as f:
            self.assertIn('datetime="2026-11-20T00:47+02:00"', f.read())
        self.assertEqual(stats["changed"], 0)
        self.assertIn("עודכן לאחרונה בתאריך 20.11.2026<", build_site.lastmod_html("2026-11-20"))  # older date-only entries

    def _zip(self, name, extra_trip=False):
        files = dict(FILES)
        if extra_trip:
            files["trips.txt"] += "100,WK,t8,,0,\n"
            files["stop_times.txt"] += (
                "t8,10:00:00,10:00:00,1,1\nt8,10:04:00,10:04:00,2,2\nt8,10:30:00,10:30:00,3,3\n"
            )
        path = os.path.join(self.tmp, name)
        with zipfile.ZipFile(path, "w") as zf:
            for fname, text in files.items():
                zf.writestr(fname, text)
        return path

    def _cfg(self, manifest, days=0, **extra):
        day = _dt.timedelta(days=days)
        return dict(self.cfg, today=TODAY + day, now=NOW + day,
                    manifest=os.path.join(self.tmp, manifest), **extra)

    def test_dates_ignore_design_and_address(self):
        base = self._zip("base.zip")
        build_site.build(base, os.path.join(self.tmp, "d1"), self._cfg("m_design.json"))
        stats = build_site.build(base, os.path.join(self.tmp, "d2"), self._cfg(
            "m_design.json", days=1, site_name="שם אחר", base_url="https://example.org/"))
        self.assertEqual(stats["changed"], 0)
        with open(os.path.join(self.tmp, "d2", "index.html"), encoding="utf-8") as f:
            self.assertIn('datetime="2026-11-20T00:47+02:00"', f.read())

    def test_timetable_change_moves_only_affected_pages(self):
        build_site.build(self._zip("a.zip"), os.path.join(self.tmp, "t1"), self._cfg("m_data.json"))
        stats = build_site.build(self._zip("b.zip", extra_trip=True), os.path.join(self.tmp, "t2"),
                                 self._cfg("m_data.json", days=1))
        changed = {u.split("olim-app.com/", 1)[1] for u in stats["changed_urls"]}
        self.assertEqual(changed, {f"lines/{LINE}.html", "stops/21001.html", "stops/21002.html", "stops/31003.html"})
        with open(os.path.join(self.tmp, "t2", f"lines/{LINE}.html"), encoding="utf-8") as f:
            self.assertIn('datetime="2026-11-21T00:47+02:00"', f.read())

    def test_switching_hash_method_keeps_existing_dates(self):
        manifest = os.path.join(self.tmp, "m_old.json")
        with open(manifest, "w", encoding="utf-8") as f:
            json.dump({"index.html": {"hash": "0123456789abcdef", "lastmod": "2026-11-20T13:31+02:00"}}, f)
        stats = build_site.build(self._zip("c.zip"), os.path.join(self.tmp, "o1"),
                                 self._cfg("m_old.json", days=1))
        with open(manifest, encoding="utf-8") as f:
            entry = json.load(f)["index.html"]
        self.assertEqual(entry["lastmod"], "2026-11-20T13:31+02:00")
        self.assertIn("data_hash", entry)
        self.assertNotIn("https://olim-app.com/index.html", stats["changed_urls"])

    def test_stop_view_is_one_block(self):
        stop = self.read("stops/21001.html")
        self.assertEqual(stop.count("<h2>מבט על התחנה</h2>"), 1)
        block = stop.split("<h2>מבט על התחנה</h2>", 1)[1].split("</section>", 1)[0]
        self.assertIn('data-goatcounter-click="streetview-link"', block)
        self.assertIn('data-goatcounter-click="stop-review"', block)
        self.assertNotIn("איך התחנה נראית", stop)
        self.assertNotIn("עמדתם בתחנה הזו?", stop)
        # a stop without coordinates still gets the review part
        cfg = build_site.config()
        html_text = build_site.stop_view_block(cfg, {"stop_id": "9", "stop_code": "9", "stop_lat": "", "stop_lon": ""})
        self.assertIn("stop-review", html_text)
        self.assertNotIn("streetview-link", html_text)

    def test_forms(self):
        stop = self.read("stops/21001.html")
        self.assertIn("viewform?usp=pp_url&amp;entry.490134728=21001", stop)
        self.assertIn('data-goatcounter-click="stop-review"', stop)
        self.assertIn('data-goatcounter-click="signup-open"', self.read("notify.html"))

    def test_html_is_escaped(self):
        self.assertEqual(build_site.e('<b>"x"</b>'), "&lt;b&gt;&quot;x&quot;&lt;/b&gt;")

    def test_unknown_city_fails_with_hint(self):
        cfg = build_site.config()
        cfg["cities"] = ["אין כזו"]
        cfg["today"] = TODAY
        cfg["manifest"] = ""
        with self.assertRaises(SystemExit) as ctx:
            build_site.build(self.zip, os.path.join(self.tmp, "x"), cfg)
        self.assertIn("קרית אונו", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
