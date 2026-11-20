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
        self.assertIn('href="../stops/21001.html"', line)
        self.assertIn('href="../stops/31003.html"', line)
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
        block = build_site.streetview_block(cfg, {"stop_lat": "32.06", "stop_lon": "34.85"})
        self.assertIn("embed/v1/streetview?key=KEY&amp;location=32.060000,34.850000", block)
        self.assertEqual(build_site.streetview_block(cfg, {"stop_lat": "x", "stop_lon": ""}), "")

    def test_stops_are_numbered(self):
        line = self.read(f"lines/{LINE}.html")
        self.assertIn('<span class="num">1</span><a href="../stops/21001.html">', line)
        self.assertIn('<span class="num">3</span><a href="../stops/31003.html">', line)

    def test_search_box_on_every_page(self):
        for rel in ("index.html", f"lines/{LINE}.html", "stops/21001.html"):
            self.assertIn('id="find"', self.read(rel), rel)
        self.assertIn('src="../site.js"', self.read(f"lines/{LINE}.html"))
        self.assertTrue(os.path.exists(os.path.join(self.out, "site.js")))

    def test_last_updated_moves_only_on_change(self):
        self.assertIn('עודכן לאחרונה: <time datetime="2026-11-20">20.11.2026</time>', self.read("index.html"))
        self.assertIn("<lastmod>2026-11-20</lastmod>", self.read("sitemap.xml"))
        # Rebuild a day later from the same feed: nothing changed, dates stay.
        cfg = dict(self.cfg, today=TODAY + __import__("datetime").timedelta(days=1))
        out2 = os.path.join(self.tmp, "site2")
        stats = build_site.build(self.zip, out2, cfg)
        with open(os.path.join(out2, "stops/21001.html"), encoding="utf-8") as f:
            self.assertIn('datetime="2026-11-20"', f.read())
        self.assertEqual(stats["changed"], 0)
        # A page whose content changes gets the new date.
        cfg["site_name"] = "שם אחר"
        stats = build_site.build(self.zip, out2, cfg)
        self.assertGreater(stats["changed"], 0)
        with open(os.path.join(out2, "index.html"), encoding="utf-8") as f:
            self.assertIn('datetime="2026-11-21"', f.read())

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
