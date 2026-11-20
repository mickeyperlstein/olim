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
                        post=lambda *a: 403)


def test_read_list_skips_blank_lines(tmp_path):
    f = tmp_path / "changed.txt"
    f.write_text("https://olim-app.com/a.html\n\nhttps://olim-app.com/b.html\n", encoding="utf-8")
    assert indexnow.read_list(str(f)) == ["https://olim-app.com/a.html", "https://olim-app.com/b.html"]
