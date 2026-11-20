import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import indexnow  # noqa: E402

KEY = "58a985f1b9abf884e2c5fd66ecb0d192"


def test_payload_names_host_key_and_key_location():
    body = indexnow.payload(["https://olim-app.com/a.html"], "https://olim-app.com/", KEY)
    assert body == {
        "host": "olim-app.com",
        "key": KEY,
        "keyLocation": f"https://olim-app.com/{KEY}.txt",
        "urlList": ["https://olim-app.com/a.html"],
    }


def test_submit_batches_and_posts_json():
    sent = []

    def fake_post(url, data, headers):
        sent.append((url, json.loads(data), headers))
        return 202

    urls = [f"https://olim-app.com/p{i}.html" for i in range(25)]
    assert indexnow.submit(urls, "https://olim-app.com/", KEY, post=fake_post, batch=10) == 3
    assert [len(b["urlList"]) for _, b, _ in sent] == [10, 10, 5]
    assert sent[0][0] == "https://api.indexnow.org/indexnow"
    assert sent[0][2]["Content-Type"].startswith("application/json")


def test_nothing_changed_sends_nothing():
    def fake_post(*a):
        raise AssertionError("should not post")

    assert indexnow.submit([], "https://olim-app.com/", KEY, post=fake_post) == 0


def test_rejected_submission_raises():
    with pytest.raises(RuntimeError, match="403"):
        indexnow.submit(["https://olim-app.com/a.html"], "https://olim-app.com/", KEY,
                        post=lambda *a: 403, sleep=lambda s: None)


def test_read_list_skips_blank_lines(tmp_path):
    f = tmp_path / "changed.txt"
    f.write_text("https://olim-app.com/a.html\n\nhttps://olim-app.com/b.html\n", encoding="utf-8")
    assert indexnow.read_list(str(f)) == ["https://olim-app.com/a.html", "https://olim-app.com/b.html"]


def test_retries_when_key_not_yet_live():
    statuses = iter([403, 403, 202])
    waits = []
    n = indexnow.submit(["https://olim-app.com/a.html"], "https://olim-app.com/", KEY,
                        post=lambda *a: next(statuses), sleep=waits.append, retries=3, delay=30)
    assert n == 1
    assert waits == [30, 60]


def test_gives_up_after_retries():
    waits = []
    with pytest.raises(RuntimeError, match="403"):
        indexnow.submit(["https://olim-app.com/a.html"], "https://olim-app.com/", KEY,
                        post=lambda *a: 403, sleep=waits.append, retries=2, delay=1)
    assert waits == [1]


def test_wait_for_key_polls_until_served():
    answers = iter([None, "old", KEY])
    waits = []
    assert indexnow.wait_for_key("https://olim-app.com/", KEY, fetch=lambda url: next(answers),
                                 sleep=waits.append, attempts=5, delay=10)
    assert waits == [10, 10]
