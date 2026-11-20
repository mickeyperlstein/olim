# olim

Static pages for every bus and train line and stop in a city, built nightly from the Israel Ministry of Transport GTFS feed and published on GitHub Pages. The pages exist to be found in Google and AI search, and to measure demand for an app that rides along with you.

## How it works

`.github/workflows/pages.yml` runs every night at 22:45 UTC (about 00:45 in Israel), and on every push to `pipeline/`:

1. Runs the tests.
2. Downloads the GTFS feed.
3. Skips the rest on scheduled runs if the feed hasn't changed (its hash is kept in `data/feed.sha256`; the nightly commit of that file also keeps the repository active, so GitHub doesn't switch the schedule off).
4. Builds the site with `pipeline/build_site.py` and deploys it to GitHub Pages.
5. Commits `data/pages.json`: each page's content hash and the date it last really changed. That date is shown on the page ("עודכן לאחרונה") and used as the page's `lastmod` in the sitemap, so only pages whose content changed look fresh to search engines.

Each line page lists its stops (each linking to the stop's page), its departures from the first stop for the coming week, and a FAQ answered from the timetable, also published as schema.org `FAQPage`. Each stop page lists the lines that call there, linking back. `sitemap.xml` and `robots.txt` (which allows the AI search crawlers) are generated too. Every page loads GoatCounter, and the "notify me" button records a `notify-click` event.

## Settings

Environment variables read by `build_site.py`:

| Variable | Default |
|---|---|
| `OLIM_CITIES` | `קרית אונו\|קריית אונו` (the `עיר:` value in `stops.txt`, `\|`-separated) |
| `OLIM_BASE_URL` | `https://mickeyperlstein.github.io/olim/` |
| `OLIM_GOATCOUNTER` | `https://olim.goatcounter.com/count` |
| `OLIM_SITE_NAME` | `עולים` |

If no stop matches the city name, the build stops and prints city names found in the feed.

## Build locally

```sh
curl -fL -o /tmp/gtfs.zip https://gtfs.mot.gov.il/gtfsfiles/israel-public-transportation.zip   # GET, never HEAD
python3 -I pipeline/build_site.py /tmp/gtfs.zip site
python3 -m unittest discover -s pipeline/tests
```

Standard library only. The feed is untrusted input: it is parsed, never executed, and every value is HTML-escaped.

## Data

Timetable data: Israel Ministry of Transport. The pages are a derived version of the official feed and may contain errors or be out of date.
