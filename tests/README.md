# Lot group regression checks

Run the offline generator checks with the scraper dependencies installed:

```sh
python3 -m unittest discover -s tests
```

Run browser checks with Playwright available to Node and its Chromium installed:

```sh
node tests/lot-groups.cjs
```

Alternatively set `CHROME_PATH` to a local Chrome executable. The browser suite serves repository files through request interception; it needs no HTTP server and blocks external services. It checks desktop/mobile exclusive views, Local default, inactive image requests, incremental Later image loading, search/refined search, empty results, and keyboard activation. External map tiles are outside this offline check.
