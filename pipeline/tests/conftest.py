import datetime as dt
import os
import sys
import zipfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import build_site  # noqa: E402
from test_build import FILES, LINE, NOW, TODAY  # noqa: E402


def build_sample(tmp, **overrides):
    """Build the sample feed into tmp/site and return the site path."""
    gtfs = os.path.join(tmp, "gtfs.zip")
    with zipfile.ZipFile(gtfs, "w") as zf:
        for name, text in FILES.items():
            zf.writestr(name, text)
    cfg = build_site.config()
    cfg.update(cities=["קרית אונו"], today=TODAY, now=NOW, manifest=os.path.join(tmp, "pages.json"))
    cfg.update(overrides)
    out = os.path.join(tmp, "site")
    build_site.build(gtfs, out, cfg)
    return out


@pytest.fixture(scope="session")
def site(tmp_path_factory):
    return build_sample(str(tmp_path_factory.mktemp("site")))


@pytest.fixture(scope="session")
def site_with_maps_key(tmp_path_factory):
    return build_sample(str(tmp_path_factory.mktemp("site_key")), maps_key="TESTKEY")


@pytest.fixture(scope="session")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def phone(browser):
    """A phone-sized page that never touches the network: external requests
    (GoatCounter, Google) are answered with an empty 204 so tests stay offline."""
    ctx = browser.new_context(viewport={"width": 390, "height": 800})
    ctx.route(lambda url: not url.startswith("file://"), lambda route: route.fulfill(status=204, body=""))
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.js_errors = errors
    yield page
    ctx.close()


def file_url(site_dir, rel):
    return "file://" + os.path.join(site_dir, rel)


@pytest.fixture
def open_page(phone):
    def go(site_dir, rel):
        phone.goto(file_url(site_dir, rel))
        return phone
    return go


__all__ = ["LINE", "dt"]
