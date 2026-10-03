# AuctionSavvy — Fictional Private Demo

**🔒 Private demonstration — not open to the public.** Both pages sit behind a
password gate (client-side, session-scoped). This repo is a demo/proving-ground;
it must never be linked from auctionhunter.co.uk or promoted anywhere.

## Structure

| Path | What it is |
|---|---|
| `index.html` | Root redirect → `finds/` (Finds is the home page) |
| `finds/` | **Home.** Fixed fictional lot catalogue used to demonstrate personalised discovery. All product images are original AI-generated demo assets. |
| `houses/` | Fictional UK auction-house map with invented sale dates and a working route-planning demonstration. |
| `gate-snippet.html` | Reference copy of the login-gate snippet used in both pages. |

## Data policy

This repository contains no live marketplace catalogue, auction-house directory
or scraping workflow. All auction houses, lots, estimates, dates and locations
are invented for the private demonstration. No affiliation with a real
auctioneer or marketplace is implied.

The demo password gate remains client-side and session-scoped. The repository is
separate from any live commercial service.

## Local preview

```bash
python3 -m http.server 8899
# open http://localhost:8899/
```

## Shared site header

All five pages use the scoped `.as-header` markup and `assets/header.css` for consistent branding, navigation, readable controls and responsive wrapping. `assets/header.js` keeps in-page destinations clear of the header when its height changes. Header checks are documented in `tests/README.md`.
