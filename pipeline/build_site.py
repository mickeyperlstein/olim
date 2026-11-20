"""Build static line and stop pages from the Israel Ministry of Transport GTFS feed.

Usage:
    python -I pipeline/build_site.py GTFS_ZIP OUT_DIR

Settings come from environment variables (see config() below). The feed is
untrusted data: it is only parsed, never executed, and every value written to
HTML is escaped.
"""

import csv
import hashlib
import datetime as dt
import html
import io
import json
import os
import re
import statistics
import sys
import zipfile
from collections import defaultdict

# ---------------------------------------------------------------- settings


def config():
    cities = os.environ.get("OLIM_CITIES", "קרית אונו|קריית אונו")
    return {
        "cities": [c.strip() for c in cities.split("|") if c.strip()],
        "base_url": os.environ.get(
            "OLIM_BASE_URL", "https://mickeyperlstein.github.io/olim/"
        ).rstrip("/")
        + "/",
        "site_name": os.environ.get("OLIM_SITE_NAME", "עולים"),
        "goatcounter": os.environ.get(
            "OLIM_GOATCOUNTER", "https://olim.goatcounter.com/count"
        ),
        "today": dt.date.today(),
        # Optional Google Maps Embed API key (free; restrict it to the site's domain).
        "maps_key": os.environ.get("OLIM_MAPS_KEY", "").strip(),
        # Page hashes and last-changed dates, committed to the repo by the workflow.
        "manifest": os.environ.get("OLIM_MANIFEST", "data/pages.json"),
    }


DAY_TYPES = [
    ("weekday", "ראשון–חמישי", ["sunday", "monday", "tuesday", "wednesday", "thursday"]),
    ("friday", "שישי", ["friday"]),
    ("saturday", "שבת", ["saturday"]),
]

ROUTE_TYPES = {"0": "רכבת קלה", "1": "מטרו", "2": "רכבת", "3": "אוטובוס", "715": "שירות לפי דרישה"}

CITY_RE = re.compile(r"עיר:\s*(.*?)\s*(?:רציף:|קומה:|$)")

# ---------------------------------------------------------------- reading


def read_table(zf, name):
    """Yield rows of one GTFS file as dicts, streaming (stop_times is huge)."""
    with zf.open(name) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        yield from csv.DictReader(text)


def stop_city(stop):
    m = CITY_RE.search(stop.get("stop_desc") or "")
    return m.group(1).strip() if m else ""


def to_minutes(hhmmss):
    """GTFS times can pass 24:00 for trips after midnight."""
    h, m, *_ = (hhmmss or "0:0").split(":")
    return int(h) * 60 + int(m)


def fmt_time(minutes):
    return f"{(minutes // 60) % 24:02d}:{minutes % 60:02d}"


def fmt_when(minutes):
    """For sentences: marks trips that leave after midnight."""
    return fmt_time(minutes) + (" (אחרי חצות)" if minutes >= 24 * 60 else "")


def clean_end(name):
    """'Stop name-City' -> 'Stop name (City)'; drops the feed's '-1#' suffix."""
    name = re.sub(r"-\d+#?$", "", name.strip()).rstrip("#").strip()
    if "-" in name:
        place, city = name.rsplit("-", 1)
        return f"{place.strip()} ({city.strip()})"
    return name


def route_ends(route):
    long_name = route.get("route_long_name") or ""
    if "<->" in long_name:
        a, b = long_name.split("<->", 1)
        return clean_end(a), clean_end(b)
    return long_name.strip(), ""


def load(gtfs_path, cities):
    zf = zipfile.ZipFile(gtfs_path)

    stops = {s["stop_id"]: s for s in read_table(zf, "stops.txt")}
    for s in stops.values():
        s["city"] = stop_city(s)

    city_stop_ids = {sid for sid, s in stops.items() if s["city"] in cities}
    if not city_stop_ids:
        seen = sorted({s["city"] for s in stops.values() if s["city"]})
        raise SystemExit(
            f"No stops matched {cities}. Example city names in the feed: {seen[:40]}"
        )

    agencies = {a["agency_id"]: a for a in read_table(zf, "agency.txt")}
    routes = {r["route_id"]: r for r in read_table(zf, "routes.txt")}
    services = {c["service_id"]: c for c in read_table(zf, "calendar.txt")}
    trips = {t["trip_id"]: t for t in read_table(zf, "trips.txt")}

    # Pass 1: which trips call at a stop in the chosen cities.
    city_trips = set()
    for st in read_table(zf, "stop_times.txt"):
        if st["stop_id"] in city_stop_ids:
            city_trips.add(st["trip_id"])
    city_trips &= trips.keys()

    # Pass 2: the full stop sequence of those trips.
    calls = defaultdict(list)  # trip_id -> [(seq, stop_id, minutes)]
    for st in read_table(zf, "stop_times.txt"):
        if st["trip_id"] in city_trips:
            t = st.get("departure_time") or st.get("arrival_time")
            calls[st["trip_id"]].append((int(st["stop_sequence"]), st["stop_id"], to_minutes(t)))
    for seq in calls.values():
        seq.sort()

    return stops, agencies, routes, services, trips, calls


# ---------------------------------------------------------------- model


WEEKDAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def day_types_of(service, today):
    """Day types on which this service runs during the coming week.

    The feed holds several weeks of services; only the week starting today
    counts, so the pages show the timetable that is actually about to run.
    """
    if not service:
        return []
    start = dt.datetime.strptime(service["start_date"], "%Y%m%d").date()
    end = dt.datetime.strptime(service["end_date"], "%Y%m%d").date()
    found = set()
    for i in range(7):
        d = today + dt.timedelta(days=i)
        name = WEEKDAY_NAMES[d.weekday()]
        if start <= d <= end and service.get(name) == "1":
            found.update(key for key, _, days in DAY_TYPES if name in days)
    return [key for key, _, _ in DAY_TYPES if key in found]


def line_key(route):
    """The Ministry splits one public line into a route per direction and
    variant. route_desc is 'licence-direction-variant' (e.g. '10001-1-0'):
    the licence number plus operator identifies the line itself."""
    parts = (route.get("route_desc") or "").split("-")
    if len(parts) >= 2 and parts[0].strip().isdigit():
        return f"{parts[0].strip()}-{route.get('agency_id', '')}", parts[1].strip() or "1"
    return f"r{route['route_id']}", "1"


def build_model(stops, agencies, routes, services, trips, calls, today):
    empty_days = lambda: {key: set() for key, _, _ in DAY_TYPES}  # noqa: E731

    # trip ids grouped by line, then by direction, then by variant (route)
    grouped = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for trip_id, seq in calls.items():
        route = routes.get(trips[trip_id]["route_id"])
        if seq and route:
            key, direction = line_key(route)
            grouped[key][direction][route["route_id"]].append(trip_id)

    lines = {}
    stop_lines = defaultdict(dict)  # stop_id -> (line key, direction) -> {day: [minutes]}

    for key, by_dir in grouped.items():
        directions = []
        for direction in sorted(by_dir):
            variants = by_dir[direction]
            # The main variant is the one with most trips; its longest trip gives the stop list.
            main = max(variants, key=lambda r: (len(variants[r]), r))
            rep = max(variants[main], key=lambda t: (len(calls[t]), -calls[t][0][2]))
            rep_calls = calls[rep]
            start = rep_calls[0][2]

            departures = empty_days()
            per_stop = defaultdict(empty_days)
            for trip_ids in variants.values():
                for t in trip_ids:
                    for day in day_types_of(services.get(trips[t]["service_id"]), today):
                        departures[day].add(calls[t][0][2])
                        for _, sid, minutes in calls[t]:
                            per_stop[sid][day].add(minutes)

            origin, dest = route_ends(routes[main])
            directions.append({
                "id": direction,
                "origin": origin,
                "dest": dest,
                "stops": [(sid, m - start) for _, sid, m in rep_calls if sid in stops],
                "departures": {d: sorted(v) for d, v in departures.items()},
                "duration": rep_calls[-1][2] - start,
                "variants": len(variants),
            })
            for sid, days in per_stop.items():
                stop_lines[sid][(key, direction)] = {d: sorted(v) for d, v in days.items()}

        first_route = routes[next(iter(next(iter(by_dir.values()))))]
        agency = agencies.get(first_route.get("agency_id"), {})
        lines[key] = {
            "id": key,
            "number": first_route.get("route_short_name") or "",
            "type": ROUTE_TYPES.get(first_route.get("route_type", ""), "תחבורה ציבורית"),
            "operator": agency.get("agency_name", ""),
            "directions": directions,
        }

    return lines, stop_lines


def headway(times):
    """Typical gap between departures, 07:00–19:00, in minutes."""
    day = [t for t in times if 7 * 60 <= t < 19 * 60]
    gaps = [b - a for a, b in zip(day, day[1:]) if b > a]
    return round(statistics.median(gaps)) if gaps else None


def natural_key(line):
    m = re.match(r"(\d+)(.*)", line["number"])
    return (int(m.group(1)), m.group(2)) if m else (10**6, line["number"])


# ---------------------------------------------------------------- html

e = html.escape


def stop_slug(stop):
    return re.sub(r"[^0-9A-Za-z_-]", "_", stop.get("stop_code") or stop["stop_id"])


def line_slug(line):
    return re.sub(r"[^0-9A-Za-z_-]", "_", line["id"])


def page(cfg, *, title, description, path, body, depth, faq=None):
    root = "../" * depth
    ld = ""
    if faq:
        data = {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
                for q, a in faq
            ],
        }
        ld = '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + "</script>"
    return f"""<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{e(cfg['base_url'] + path)}">
<link rel="stylesheet" href="{root}style.css">
<script src="{root}site.js" defer></script>
{ld}
<script data-goatcounter="{e(cfg['goatcounter'])}" async src="//gc.zgo.at/count.js"></script>
</head>
<body>
<header class="top"><div class="wrap">
<a class="brand" href="{root}index.html">{e(cfg['site_name'])}</a>
<form class="find" role="search" onsubmit="return false">
<label for="find" class="sr">חיפוש בעמוד</label>
<input id="find" type="search" placeholder="חיפוש קו או תחנה בעמוד" autocomplete="off" aria-controls="find-results" aria-expanded="false">
<ul id="find-results" class="find-results" hidden></ul>
</form>
</div></header>
<main class="wrap">
{body}
<section class="cta">
<h2>רוצים שהאפליקציה תיסע איתכם?</h2>
<p>אנחנו בונים אפליקציה שמזהה לבד באיזה קו אתם, מתריעה כשהאוטובוס סוטה מהמסלול ואומרת מתי לרדת.</p>
<a class="cta-btn" href="{root}notify.html" data-goatcounter-click="notify-click" data-goatcounter-title="{e(title)}">עדכנו אותי כשהיא יוצאת</a>
</section>
</main>
<footer class="wrap foot">
<p>עודכן לאחרונה: {LASTMOD}. נתוני לוחות זמנים: משרד התחבורה. המידע עשוי להשתנות. יש לבדוק במקורות הרשמיים לפני הנסיעה.</p>
</footer>
</body>
</html>
"""


def faq_block(faq):
    items = "".join(f"<div class=\"qa\"><h3>{e(q)}</h3><p>{e(a)}</p></div>" for q, a in faq)
    return f'<section class="card"><h2>שאלות נפוצות</h2>{items}</section>'


def line_ends(line):
    d0 = line["directions"][0]
    if len(line["directions"]) > 1 or not d0["dest"]:
        a, b = d0["origin"], d0["dest"] or line["directions"][-1]["origin"]
    else:
        a, b = d0["origin"], d0["dest"]
    if not b or a == b:
        return f"{a} (מעגלי)" if a else ""
    return f"{a} – {b}"


def line_title(line):
    return f"קו {line['number']} {line_ends(line)}".strip()


def find_direction(line, direction):
    return next((d for d in line["directions"] if d["id"] == direction), line["directions"][0])


def line_faq(line):
    n = line["number"]
    dirs = line["directions"]
    d0 = dirs[0]
    wk = d0["departures"]["weekday"]
    fri = d0["departures"]["friday"]
    origin = d0["origin"] or "תחנת המוצא"
    faq = []
    if wk:
        faq.append((f"מתי יוצא האוטובוס הראשון של קו {n}?", f"בימים א׳–ה׳ ב־{fmt_time(wk[0])} מ{origin}."))
        faq.append((f"מתי יוצא האוטובוס האחרון של קו {n}?", f"בימים א׳–ה׳ ב־{fmt_when(wk[-1])} מ{origin}."))
    for d in dirs[1:2]:
        back = d["departures"]["weekday"]
        if back and d["origin"]:
            faq.append((f"מתי יוצא קו {n} הראשון מ{d['origin']}?", f"בימים א׳–ה׳ ב־{fmt_time(back[0])}, והאחרון ב־{fmt_when(back[-1])}."))
    if wk:
        gap = headway(wk)
        if gap:
            faq.append((f"כל כמה זמן יש קו {n}?", f"בשעות היום, בערך כל {gap} דקות (ימים א׳–ה׳)."))
    if fri:
        faq.append((f"עד מתי פועל קו {n} ביום שישי?", f"היציאה האחרונה ביום שישי ב־{fmt_when(fri[-1])} מ{origin}."))
    sat = sorted(t for d in dirs for t in d["departures"]["saturday"])
    if sat:
        faq.append((f"האם קו {n} פועל בשבת?", f"כן. היציאה הראשונה בשבת ב־{fmt_time(sat[0])}."))
    else:
        faq.append((f"האם קו {n} פועל בשבת?", "לפי לוח הזמנים הרשמי, הקו לא פועל בשבת."))
    if d0["duration"] > 0 and d0["dest"] and d0["dest"] != d0["origin"]:
        faq.append((f"כמה זמן לוקחת הנסיעה בקו {n}?", f"כ־{d0['duration']} דקות לפי לוח הזמנים, מ{origin} ל{d0['dest']}. בעומס זה יכול לקחת יותר."))
    if line["operator"]:
        faq.append((f"מי מפעיל את קו {n}?", f"{line['operator']}."))
    return faq


def times_block(departures):
    parts = []
    for key, label, _ in DAY_TYPES:
        times = departures[key]
        if times:
            chips = "".join(f"<li>{fmt_time(t)}</li>" for t in times)
            parts.append(f"<h4>{label}</h4><ul class=\"times\">{chips}</ul>")
        else:
            parts.append(f"<h4>{label}</h4><p class=\"muted\">אין נסיעות.</p>")
    return "".join(parts)


def direction_block(d, stops):
    rows = []
    for i, (sid, offset) in enumerate(d["stops"], 1):
        s = stops[sid]
        rows.append(
            f'<li><span class="stop"><span class="num">{i}</span>'
            f'<a href="../stops/{stop_slug(s)}.html">{e(s["stop_name"])}</a></span>'
            f'<span class="muted">+{offset} דק׳</span></li>'
        )
    meta = f"{len(d['stops'])} תחנות"
    if d["duration"] > 0:
        meta += f" · כ־{d['duration']} דק׳ נסיעה"
    if d["variants"] > 1:
        meta += f" · {d['variants']} וריאציות מסלול (התחנות לפי המסלול העיקרי)"
    dest = d["dest"] or d["origin"]
    return f"""<section class="card" id="dir-{e(d['id'])}">
<h2>לכיוון {e(dest)}</h2>
<p class="muted">מ{e(d['origin'])} · {e(meta)}</p>
<h3>תחנות</h3><ol class="route">{''.join(rows)}</ol>
<h3>שעות יציאה מ{e(d['origin'])}</h3>{times_block(d['departures'])}
</section>"""


def render_line(cfg, line, stops):
    title = line_title(line)
    faq = line_faq(line)
    jumps = " · ".join(
        f'<a href="#dir-{e(d["id"])}">לכיוון {e(d["dest"] or d["origin"])}</a>' for d in line["directions"]
    )
    summary = " · ".join(x for x in (line["type"], line["operator"]) if x)
    body = f"""
<nav class="crumbs"><a href="../index.html">קווים</a> › קו {e(line['number'])}</nav>
<section class="card hero">
<div class="badge">{e(line['number'])}</div>
<div><h1>{e(title)}</h1><p class="muted">{e(summary)}</p><p class="jumps">{jumps}</p></div>
</section>
{''.join(direction_block(d, stops) for d in line['directions'])}
{faq_block(faq)}
"""
    desc = f"לוח זמנים, תחנות ושאלות נפוצות על {title}, בשני הכיוונים. מבוסס על נתוני משרד התחבורה."
    return page(cfg, title=f"{title} | זמנים ותחנות", description=desc,
                path=f"lines/{line_slug(line)}.html", body=body, depth=1, faq=faq)


def coords(stop):
    try:
        lat, lon = float(stop.get("stop_lat", "")), float(stop.get("stop_lon", ""))
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return f"{lat:.6f},{lon:.6f}"


def streetview_block(cfg, stop):
    """A Street View link, plus a tap-to-load embed when a key is configured.
    Nothing from Google loads until the visitor taps."""
    loc = coords(stop)
    if not loc:
        return ""
    link = f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={loc}"
    embed = ""
    if cfg.get("maps_key"):
        src = f"https://www.google.com/maps/embed/v1/streetview?key={cfg['maps_key']}&location={loc}&fov=80"
        embed = (
            f'<button type="button" class="sv-btn" data-src="{e(src)}" data-goatcounter-click="streetview-open" '
            "onclick=\"var f=document.createElement('iframe');f.src=this.dataset.src;f.className='sv';"
            "f.title='מבט רחוב על התחנה';f.loading='lazy';f.allowFullscreen=true;"
            "f.referrerPolicy='no-referrer-when-downgrade';this.replaceWith(f);\">הצגת מבט רחוב על התחנה</button>"
        )
    return f"""<section class="card"><h2>איך התחנה נראית</h2>
{embed}
<p class="muted"><a href="{e(link)}" target="_blank" rel="noopener" data-goatcounter-click="streetview-link">פתיחה ב־Google Street View</a>. במקומות מסוימים אין מבט רחוב ליד התחנה.</p>
</section>"""


def render_stop(cfg, stop, serving, lines):
    name = stop["stop_name"]
    city = stop["city"]
    items = []
    first_times = []
    for (key, direction), days in sorted(serving.items(), key=lambda kv: (natural_key(lines[kv[0][0]]), kv[0][1])):
        line = lines[key]
        d = find_direction(line, direction)
        wk = days["weekday"]
        when = f"{fmt_time(wk[0])}–{fmt_time(wk[-1])}" if wk else "לא בימים א׳–ה׳"
        if wk:
            first_times.append(wk[0])
        items.append(
            f'<li><a href="../lines/{line_slug(line)}.html#dir-{e(direction)}"><span class="mini">{e(line["number"])}</span> '
            f'לכיוון {e(d["dest"] or d["origin"])}</a><span class="muted">{e(when)}</span></li>'
        )
    numbers = sorted({lines[k]["number"] for k, _ in serving}, key=lambda n: natural_key({"number": n}))
    faq = [(f"אילו קווים עוצרים בתחנה {name}?", "קווים " + ", ".join(numbers) + ".")]
    if first_times:
        faq.append((f"מתי עובר האוטובוס הראשון בתחנה {name}?", f"בימים א׳–ה׳ בסביבות {fmt_time(min(first_times))}."))
    code = stop.get("stop_code") or ""
    title = f"תחנת {name}" + (f", {city}" if city else "")
    body = f"""
<nav class="crumbs"><a href="../index.html">קווים</a> › תחנה</nav>
<section class="card"><h1>{e(title)}</h1>
<p class="muted">{('מספר תחנה ' + e(code) + ' · ') if code else ''}{len(numbers)} קווים עוצרים כאן</p></section>
<section class="card"><h2>קווים בתחנה</h2><ul class="lines">{''.join(items)}</ul></section>
{streetview_block(cfg, stop)}
{faq_block(faq)}
"""
    desc = f"אילו קווים עוצרים ב{title}, ומתי. מבוסס על נתוני משרד התחבורה."
    return page(cfg, title=f"{title} | קווים וזמנים", description=desc,
                path=f"stops/{stop_slug(stop)}.html", body=body, depth=1, faq=faq)


def render_index(cfg, lines):
    items = "".join(
        f'<li><a href="lines/{line_slug(l)}.html"><span class="mini">{e(l["number"])}</span> {e(line_ends(l))}</a>'
        f'<span class="muted">{e(l["operator"])}</span></li>'
        for l in sorted(lines.values(), key=lambda l: (natural_key(l), l["operator"]))
    )
    cities = " / ".join(cfg["cities"][:1])
    body = f"""
<section class="card"><h1>קווי אוטובוס ורכבת ב{e(cities)}</h1>
<p class="muted">כל הקווים שעוצרים בעיר, עם תחנות ושעות יציאה.</p></section>
<section class="card"><ul class="lines">{items}</ul></section>
"""
    return page(cfg, title=f"קווי תחבורה ציבורית ב{cities}", description=f"כל קווי האוטובוס והרכבת ב{cities}: תחנות, שעות ותשובות לשאלות נפוצות.",
                path="index.html", body=body, depth=0)


def render_notify(cfg):
    body = """
<section class="card"><h1>האפליקציה בדרך</h1>
<p>תודה שהתעניינתם. אנחנו בודקים כמה אנשים רוצים אפליקציה שנוסעת איתם: מזהה באיזה קו הם, מתריעה על סטיות ואומרת מתי לרדת.</p>
<p>ההרשמה לעדכונים תיפתח בקרוב.</p></section>
"""
    return page(cfg, title="האפליקציה בדרך", description="אפליקציה שנוסעת איתכם באוטובוס וברכבת.",
                path="notify.html", body=body, depth=0)


ROBOTS = """User-agent: *
Allow: /

User-agent: OAI-SearchBot
Allow: /

User-agent: Claude-SearchBot
Allow: /

User-agent: PerplexityBot
Allow: /

Sitemap: {base}sitemap.xml
"""


def write(out, rel, text):
    path = os.path.join(out, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


LASTMOD = "\x00LASTMOD\x00"  # replaced after hashing, so the date never changes the hash


def lastmod_html(iso):
    d = dt.date.fromisoformat(iso)
    return f'<time datetime="{iso}">{d.day}.{d.month}.{d.year}</time>'


def load_manifest(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def build(gtfs_path, out, cfg):
    stops, agencies, routes, services, trips, calls = load(gtfs_path, cfg["cities"])
    lines, stop_lines = build_model(stops, agencies, routes, services, trips, calls, cfg["today"])

    pages = {"index.html": render_index(cfg, lines), "notify.html": render_notify(cfg)}
    for line in lines.values():
        pages[f"lines/{line_slug(line)}.html"] = render_line(cfg, line, stops)
    for sid, serving in stop_lines.items():
        if sid in stops:
            pages[f"stops/{stop_slug(stops[sid])}.html"] = render_stop(cfg, stops[sid], serving, lines)

    # Per-page hashes: a page's date moves only when its content really changes.
    old = load_manifest(cfg["manifest"]) if cfg.get("manifest") else {}
    today = cfg["today"].isoformat()
    manifest = {}
    changed = 0
    for rel, html_text in pages.items():
        digest = hashlib.sha256(html_text.encode("utf-8")).hexdigest()[:16]
        prev = old.get(rel)
        if prev and prev.get("hash") == digest:
            manifest[rel] = prev
        else:
            manifest[rel] = {"hash": digest, "lastmod": today}
            changed += 1
        write(out, rel, html_text.replace(LASTMOD, lastmod_html(manifest[rel]["lastmod"])))
    if cfg.get("manifest"):
        os.makedirs(os.path.dirname(os.path.abspath(cfg["manifest"])), exist_ok=True)
        with open(cfg["manifest"], "w", encoding="utf-8") as f:
            json.dump(dict(sorted(manifest.items())), f, ensure_ascii=False, indent=0)
            f.write("\n")

    here = os.path.dirname(os.path.abspath(__file__))
    for asset in ("style.css", "site.js"):
        with open(os.path.join(here, asset), encoding="utf-8") as f:
            write(out, asset, f.read())
    write(out, "robots.txt", ROBOTS.format(base=cfg["base_url"]))
    listed = [p for p in manifest if p != "notify.html"]
    urls = "".join(
        f"<url><loc>{e(cfg['base_url'] + p)}</loc><lastmod>{manifest[p]['lastmod']}</lastmod></url>" for p in listed
    )
    write(out, "sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n')
    write(out, ".nojekyll", "")
    return {"lines": len(lines), "stops": len(stop_lines), "pages": len(listed), "changed": changed}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    stats = build(sys.argv[1], sys.argv[2], config())
    print(json.dumps(stats))
