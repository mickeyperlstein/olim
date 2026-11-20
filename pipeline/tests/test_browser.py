"""Browser tests: the built pages, opened in headless Chromium at phone width."""

from test_build import LINE

LINE_PAGE = f"lines/{LINE}.html"
STOP_PAGE = "stops/21001.html"


def test_pages_load_without_js_errors(site, open_page):
    for rel in ("index.html", LINE_PAGE, STOP_PAGE, "notify.html"):
        page = open_page(site, rel)
        page.wait_for_load_state("load")
        assert page.js_errors == [], rel


def test_no_horizontal_scroll_on_phone(site, open_page):
    for rel in ("index.html", LINE_PAGE, STOP_PAGE):
        page = open_page(site, rel)
        overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        assert overflow <= 0, f"{rel} overflows by {overflow}px"


def test_search_finds_and_jumps_to_stop(site, open_page):
    page = open_page(site, LINE_PAGE)
    page.fill("#find", "מרכזית")
    results = page.locator("#find-results button")
    assert results.count() >= 1
    assert "תחנה מרכזית" in results.first.inner_text()
    results.first.click()
    assert page.locator(".hit").count() == 1
    assert page.locator("#find-results").is_hidden()


def test_search_enter_picks_first_and_ignores_final_letters(site, open_page):
    page = open_page(site, LINE_PAGE)
    page.fill("#find", "צומת")  # matches צומת whether typed with final or regular letters
    page.press("#find", "Enter")
    assert page.locator(".hit").count() == 1


def test_search_no_match_message(site, open_page):
    page = open_page(site, LINE_PAGE)
    page.fill("#find", "zzzz")
    assert page.locator("#find-results .none").inner_text() == "לא נמצא בעמוד הזה"


def test_search_escape_closes(site, open_page):
    page = open_page(site, LINE_PAGE)
    page.fill("#find", "מרכזית")
    page.press("#find", "Escape")
    assert page.locator("#find-results").is_hidden()


def test_search_box_stays_on_top_when_scrolled(site, open_page):
    page = open_page(site, LINE_PAGE)
    page.mouse.wheel(0, 2000)
    page.wait_for_timeout(100)
    box = page.locator(".top").bounding_box()
    assert box["y"] == 0


def test_stops_numbered_in_order(site, open_page):
    page = open_page(site, LINE_PAGE)
    nums = page.locator("#dir-1 .route .num").all_inner_texts()
    assert nums == [str(i) for i in range(1, len(nums) + 1)]
    assert len(nums) == 3


def test_streetview_embed_loads_only_on_tap(site_with_maps_key, open_page):
    page = open_page(site_with_maps_key, STOP_PAGE)
    assert page.locator("iframe.sv").count() == 0
    page.click(".sv-btn")
    frame = page.locator("iframe.sv")
    assert frame.count() == 1
    src = frame.get_attribute("src")
    assert "embed/v1/streetview?key=TESTKEY" in src and "location=32.060000,34.850000" in src


def test_no_streetview_button_without_key(site, open_page):
    page = open_page(site, STOP_PAGE)
    assert page.locator(".sv-btn").count() == 0
    assert page.locator('a[data-goatcounter-click="streetview-link"]').count() == 1


def test_stop_review_link_prefilled(site, open_page):
    page = open_page(site, STOP_PAGE)
    href = page.locator('a[data-goatcounter-click="stop-review"]').get_attribute("href")
    assert href.endswith("entry.490134728=21001")
