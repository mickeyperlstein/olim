"""Tell IndexNow search engines (Bing, Yandex, Seznam, Naver...) which pages changed.

Usage:
    python -I pipeline/indexnow.py CHANGED_URLS_FILE

Reads one URL per line (written by build_site.py) and submits them to
api.indexnow.org, which shares them with every participating engine. The key
is public by design: the same key is served at https://<site>/<key>.txt.
"""

import json
import sys
import time
import urllib.parse
import urllib.request

ENDPOINT = "https://api.indexnow.org/indexnow"
MAX_BATCH = 10000  # IndexNow's limit per request


def read_list(path):
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def payload(urls, base_url, key):
    base = base_url.rstrip("/") + "/"
    return {
        "host": urllib.parse.urlparse(base).hostname,
        "key": key,
        "keyLocation": f"{base}{key}.txt",
        "urlList": list(urls),
    }


def http_post(url, data, headers):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as err:
        return err.code


def http_get_text(url):
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.read().decode("utf-8", "replace").strip()
    except (urllib.error.URLError, OSError):
        return None


def wait_for_key(base_url, key, fetch=http_get_text, sleep=time.sleep, attempts=20, delay=15):
    """Right after a deploy the CDN may not serve the key file yet; IndexNow
    checks it and refuses (403) until it does. Poll until the key is live."""
    url = f"{base_url.rstrip('/')}/{key}.txt"
    for i in range(attempts):
        if fetch(url) == key:
            return True
        if i < attempts - 1:
            sleep(delay)
    return False


def submit(urls, base_url, key, post=http_post, batch=MAX_BATCH, sleep=time.sleep, retries=4, delay=60):
    """Submit urls in batches, retrying refusals with growing waits; returns requests sent."""
    sent = 0
    for i in range(0, len(urls), batch):
        body = json.dumps(payload(urls[i:i + batch], base_url, key)).encode("utf-8")
        for attempt in range(1, retries + 1):
            status = post(ENDPOINT, body, {"Content-Type": "application/json; charset=utf-8"})
            if status in (200, 202):
                break
            if attempt == retries:
                raise RuntimeError(f"IndexNow rejected the submission: HTTP {status}")
            sleep(delay * attempt)
        sent += 1
    return sent


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    sys.path.insert(0, __import__("os").path.dirname(__file__))
    import build_site

    cfg = build_site.config()
    urls = read_list(sys.argv[1])
    if urls and not wait_for_key(cfg["base_url"], cfg["indexnow_key"]):
        raise SystemExit("IndexNow: key file never became reachable; not submitting")
    n = submit(urls, cfg["base_url"], cfg["indexnow_key"])
    print(f"IndexNow: {len(urls)} changed pages in {n} request(s)")
