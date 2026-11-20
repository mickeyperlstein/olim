"""Build static line and stop pages from the Israel Ministry of Transport GTFS feed.

Usage:
    python -I pipeline/build_site.py GTFS_ZIP OUT_DIR

Settings come from environment variables (see config() below). The feed is
untrusted data: it is only parsed, never executed, and every value written to
HTML is escaped.
"""

import csv
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


def build_model(stops, agencies, routes, services, trips, calls, today):
    lines = {}
    stop_lines = defaultdict(dict)  # stop_id -> route_id -> {day: [minutes]}

    by_route = defaultdict(list)
    for trip_id, seq in calls.items():
        if seq:
            by_route[trips[trip_id]["route_id"]].append(trip_id)

    for route_id, trip_ids in by_route.items():
        route = routes.get(route_id)
        if not route:
            continue
        # Representative trip: the one with the most stops.
        rep = max(trip_ids, key=lambda t: (len(calls[t]), -calls[t][0][2]))
        rep_calls = calls[rep]
        start = rep_calls[0][2]

        departures = {key: set() for key, _, _ in DAY_TYPES}
        per_stop = defaultdict(lambda: {key: set() for key, _, _ in DAY_TYPES})
        for t in trip_ids:
            days = day_types_of(services.get(trips[t]["service_id"]), today)
            for day in days:
                departures[day].add(calls[t][0][2])
                for _, sid, minutes in calls[t]:
                    per_stop[sid][day].add(minutes)

        origin, dest = route_ends(route)
        agency = agencies.get(route.get("agency_id"), {})
        lines[route_id] = {
            "id": route_id,
            "number": route.get("route_short_name") or "",
            "type": ROUTE_TYPES.get(route.get("route_type", ""), "תחבורה ציבורית"),
            "origin": origin,
            "dest": dest,
            "operator": agency.get("agency_name", ""),
            "operator_url": agency.get("agency_url", ""),
            "stops": [(sid, m - start) for _, sid, m in rep_calls if sid in stops],
            "departures": {d: sorted(v) for d, v in departures.items()},
            "duration": rep_calls[-1][2] - start,
        }
        for sid, days in per_stop.items():
            stop_lines[sid][route_id] = {d: sorted(v) for d, v in days.items()}

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
{ld}
<script data-goatcounter="{e(cfg['goatcounter'])}" async src="//gc.zgo.at/count.js"></script>
</head>
<body>
<header class="top"><div class="wrap"><a class="brand" href="{root}index.html">{e(cfg['site_name'])}</a></div></header>
<main class="wrap">
{body}
<section class="cta">
<h2>רוצים שהאפליקציה תיסע איתכם?</h2>
<p>אנחנו בונים אפליקציה שמזהה לבד באיזה קו אתם, מתריעה כשהאוטובוס סוטה מהמסלול ואומרת מתי לרדת.</p>
<a class="cta-btn" href="{root}notify.html" data-goatcounter-click="notify-click" data-goatcounter-title="{e(title)}">עדכנו אותי כשהיא יוצאת</a>
</section>
</main>
<footer class="wrap foot">
<p>נתוני לוחות זמנים: משרד התחבורה. המידע עשוי להשתנות. יש לבדוק במקורות הרשמיים לפני הנסיעה.</p>
</footer>
</body>
</html>
"""


def faq_block(faq):
    items = "".join(f"<div class=\"qa\"><h3>{e(q)}</h3><p>{e(a)}</p></div>" for q, a in faq)
    return f'<section class="card"><h2>שאלות נפוצות</h2>{items}</section>'


def line_title(line):
    ends = f"{line['origin']} ← {line['dest']}" if line["dest"] else line["origin"]
    return f"קו {line['number']} {ends}"


def line_faq(line, stops):
    n = line["number"]
    wk = line["departures"]["weekday"]
    fri = line["departures"]["friday"]
    sat = line["departures"]["saturday"]
    origin = line["origin"] or "תחנת המוצא"
    faq = []
    if wk:
        faq.append((f"מתי יוצא האוטובוס הראשון של קו {n}?", f"בימים א׳–ה׳ ב־{fmt_time(wk[0])} מ{origin}."))
        faq.append((f"מתי יוצא האוטובוס האחרון של קו {n}?", f"בימים א׳–ה׳ ב־{fmt_when(wk[-1])} מ{origin}."))
        gap = headway(wk)
        if gap:
            faq.append((f"כל כמה זמן יש קו {n}?", f"בשעות היום, בערך כל {gap} דקות (ימים א׳–ה׳)."))
    if fri:
        faq.append((f"עד מתי פועל קו {n} ביום שישי?", f"היציאה האחרונה ביום שישי ב־{fmt_when(fri[-1])}."))
    if sat:
        faq.append((f"האם קו {n} פועל בשבת?", f"כן. היציאה הראשונה בשבת ב־{fmt_time(sat[0])}."))
    else:
        faq.append((f"האם קו {n} פועל בשבת?", "לפי לוח הזמנים הרשמי, הקו לא פועל בשבת."))
    if line["duration"] > 0 and line["dest"]:
        faq.append((f"כמה זמן לוקחת הנסיעה בקו {n}?", f"כ־{line['duration']} דקות לפי לוח הזמנים, מ{origin} ל{line['dest']}. בעומס זה יכול לקחת יותר."))
    if line["operator"]:
        faq.append((f"מי מפעיל את קו {n}?", f"{line['operator']}."))
    return faq


def times_block(departures):
    parts = []
    for key, label, _ in DAY_TYPES:
        times = departures[key]
        if times:
            chips = "".join(f"<li>{fmt_time(t)}</li>" for t in times)
            parts.append(f"<h3>{label}</h3><ul class=\"times\">{chips}</ul>")
        else:
            parts.append(f"<h3>{label}</h3><p class=\"muted\">אין נסיעות.</p>")
    return '<section class="card"><h2>שעות יציאה מתחנת המוצא</h2>' + "".join(parts) + "</section>"


def render_line(cfg, line, stops):
    title = line_title(line)
    rows = []
    for sid, offset in line["stops"]:
        s = stops[sid]
        rows.append(
            f'<li><a href="../stops/{stop_slug(s)}.html">{e(s["stop_name"])}</a>'
            f'<span class="muted">+{offset} דק׳</span></li>'
        )
    faq = line_faq(line, stops)
    summary = f"{line['type']} · {line['operator']} · {len(line['stops'])} תחנות"
    if line["duration"] > 0:
        summary += f" · כ־{line['duration']} דק׳ נסיעה"
    body = f"""
<nav class="crumbs"><a href="../index.html">קווים</a> › קו {e(line['number'])}</nav>
<section class="card hero">
<div class="badge">{e(line['number'])}</div>
<div><h1>{e(title)}</h1><p class="muted">{e(summary)}</p></div>
</section>
<section class="card"><h2>תחנות הקו</h2><ol class="route">{''.join(rows)}</ol></section>
{times_block(line['departures'])}
{faq_block(faq)}
"""
    desc = f"לוח זמנים, תחנות ושאלות נפוצות על {title}. מבוסס על נתוני משרד התחבורה."
    return page(cfg, title=f"{title} | זמנים ותחנות", description=desc,
                path=f"lines/{line_slug(line)}.html", body=body, depth=1, faq=faq)


def render_stop(cfg, stop, serving, lines):
    name = stop["stop_name"]
    city = stop["city"]
    items = []
    first_times = []
    for route_id, days in sorted(serving.items(), key=lambda kv: natural_key(lines[kv[0]])):
        line = lines[route_id]
        wk = days["weekday"]
        when = f"{fmt_time(wk[0])}–{fmt_time(wk[-1])}" if wk else "לא בימים א׳–ה׳"
        if wk:
            first_times.append(wk[0])
        items.append(
            f'<li><a href="../lines/{line_slug(line)}.html"><span class="mini">{e(line["number"])}</span> '
            f'לכיוון {e(line["dest"] or line["origin"])}</a><span class="muted">{e(when)}</span></li>'
        )
    numbers = sorted({lines[r]["number"] for r in serving}, key=lambda n: natural_key({"number": n}))
    faq = [(f"אילו קווים עוצרים בתחנה {name}?", "קווים " + ", ".join(numbers) + ".")]
    if first_times:
        faq.append((f"מתי עובר האוטובוס הראשון בתחנה {name}?", f"בימים א׳–ה׳ בסביבות {fmt_time(min(first_times))}."))
    code = stop.get("stop_code") or ""
    title = f"תחנת {name}" + (f", {city}" if city else "")
    body = f"""
<nav class="crumbs"><a href="../index.html">קווים</a> › תחנה</nav>
<section class="card"><h1>{e(title)}</h1>
<p class="muted">{('מספר תחנה ' + e(code) + ' · ') if code else ''}{len(serving)} קווים עוצרים כאן</p></section>
<section class="card"><h2>קווים בתחנה</h2><ul class="lines">{''.join(items)}</ul></section>
{faq_block(faq)}
"""
    desc = f"אילו קווים עוצרים ב{title}, ומתי. מבוסס על נתוני משרד התחבורה."
    return page(cfg, title=f"{title} | קווים וזמנים", description=desc,
                path=f"stops/{stop_slug(stop)}.html", body=body, depth=1, faq=faq)


def render_index(cfg, lines):
    items = "".join(
        f'<li><a href="lines/{line_slug(l)}.html"><span class="mini">{e(l["number"])}</span> {e(line_title(l)[len("קו " + l["number"]) + 1:])}</a></li>'
        for l in sorted(lines.values(), key=natural_key)
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


def build(gtfs_path, out, cfg):
    stops, agencies, routes, services, trips, calls = load(gtfs_path, cfg["cities"])
    lines, stop_lines = build_model(stops, agencies, routes, services, trips, calls, cfg["today"])

    paths = ["index.html"]
    for line in lines.values():
        rel = f"lines/{line_slug(line)}.html"
        write(out, rel, render_line(cfg, line, stops))
        paths.append(rel)
    for sid, serving in stop_lines.items():
        if sid not in stops:
            continue
        rel = f"stops/{stop_slug(stops[sid])}.html"
        write(out, rel, render_stop(cfg, stops[sid], serving, lines))
        paths.append(rel)

    write(out, "index.html", render_index(cfg, lines))
    write(out, "notify.html", render_notify(cfg))
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.css"), encoding="utf-8") as f:
        write(out, "style.css", f.read())
    write(out, "robots.txt", ROBOTS.format(base=cfg["base_url"]))
    today = dt.date.today().isoformat()
    urls = "".join(f"<url><loc>{e(cfg['base_url'] + p)}</loc><lastmod>{today}</lastmod></url>" for p in paths)
    write(out, "sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n')
    write(out, ".nojekyll", "")
    return {"lines": len(lines), "stops": len(stop_lines), "pages": len(paths)}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    stats = build(sys.argv[1], sys.argv[2], config())
    print(json.dumps(stats))
