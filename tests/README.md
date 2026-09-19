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

Shared header coverage:

```sh
node tests/shared-headers.cjs
```

This suite checks all five documents and both Proposal views at desktop/phone widths, a 320px reflow viewport, a 786px viewport equivalent to 200% zoom from 1571px, and 200% root text size. It measures common brand/toggle geometry, readable descriptions and targets, checks keyboard focus and Map filters, search/refined controls, and Proposal switch/return navigation. It serves only repository files locally via interception but permits existing remote fonts/map dependencies. `CHROME_PATH` can select installed Chrome.
