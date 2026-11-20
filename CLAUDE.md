# Working on this repo

Test first. For every change:

1. Write or update a test that describes the new behaviour and watch it fail.
2. Make the change until it passes.
3. Run the whole suite with `python3 -m pytest` and push only when it is green.

Tests live in `pipeline/tests/`:

- `test_build.py`: the generator, run on a small sample feed (no network).
- `test_browser.py`: the built pages in headless Chromium at phone width (search, numbered stops, Street View, forms, no horizontal scroll). External requests are stubbed, so it runs offline.

The pre-push hook in `.githooks/pre-push` runs the suite and blocks the push if anything fails. Enable it once per clone with `git config core.hooksPath .githooks`. CI runs the same suite before every deploy.
