#!/usr/bin/env python3
"""
Scrape EasyLive auction dates for the Pinefinders auction-map.

GitHub Actions version: paths are driven by the repo checkout
(GITHUB_WORKSPACE), and the commit/push is handled by the workflow,
not by this script. Falls back to local Mac paths when run directly.
"""
import requests, json, re, time, sys, os
from bs4 import BeautifulSoup
from datetime import datetime, date
from pathlib import Path

DELAY = 1.5
BASE = "https://www.easyliveauction.com"
MONTHS = {"January":1,"February":2,"March":3,"April":4,"May":5,"June":6,
          "July":7,"August":8,"September":9,"October":10,"November":11,"December":12}
HEADERS = {"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# Paths
# On GitHub Actions, GITHUB_WORKSPACE is the checked-out repo root.
# Locally, fall back to the cloned repo under ~/auction-dates/auction-map.
if os.environ.get("GITHUB_WORKSPACE"):
    REPO_DIR = Path(os.environ["GITHUB_WORKSPACE"])
else:
    REPO_DIR = Path.home() / "auction-dates" / "auction-map"

# Cache the extracted house list next to the run (tmp dir works everywhere).
ALL_HOUSES_FILE = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "all_houses.json"

def load_houses():
    """Load the master house list from index.html in the repo."""
    if ALL_HOUSES_FILE.exists():
        with open(ALL_HOUSES_FILE) as f:
            return json.load(f)
    if not REPO_DIR.exists():
        print(f"ERROR: repo dir not found at {REPO_DIR}.")
        sys.exit(1)
    html_path = REPO_DIR / "index.html"
    if not html_path.exists():
        print(f"ERROR: {html_path} not found.")
        sys.exit(1)
    html = html_path.read_text()
    m = re.search(r'const ALL_HOUSES = (\[.*?\]);', html, re.DOTALL)
    if not m:
        print("ERROR: ALL_HOUSES not found in index.html")
        sys.exit(1)
    houses = json.loads(m.group(1))
    ALL_HOUSES_FILE.write_text(json.dumps(houses, indent=2))
    return houses

session = requests.Session()

def fetch(url):
    try:
        r = session.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except:
        return None

def get_ah(slug):
    """Extract the ?ah=<hash> parameter from an auctioneer's page."""
    soup = fetch(BASE + "/auctioneers/" + slug + "/")
    if not soup: return None
    for a in soup.find_all("a", href=True):
        m = re.search(r"\?ah=([a-f0-9]+)", a["href"])
        if m: return m.group(1)
    return None

def parse_date(text):
    """Parse '1st January 2026' -> '2026-01-01' if >= today."""
    m = re.search(r"(\d+)(?:st|nd|rd|th)\s+(\w+)\s+(\d{4})", text)
    if not m: return None
    day, mon, yr = m.groups()
    mo = MONTHS.get(mon)
    if not mo: return None
    try:
        d = date(int(yr), mo, int(day))
        return d.isoformat() if d >= date.today() else None
    except:
        return None

def get_sales(ah):
    """Fetch upcoming sales for an auction house hash."""
    soup = fetch(BASE + "/auctions/?ah=" + ah)
    if not soup: return []
    sales = []

    # Find auction divs (class="auc{32-hex-chars}")
    auction_divs = soup.find_all("div", class_=re.compile(r'^auc[a-f0-9]{32}$'))

    for div in auction_divs:
        # Get title from h4.auction-title
        h4 = div.find("h4", class_="auction-title")
        if not h4: continue
        title = h4.get_text(strip=True)
        if not title or len(title) < 5: continue

        # Find date in h6 tags
        for h6 in div.find_all("h6"):
            h6_text = h6.get_text(strip=True)
            ds = parse_date(h6_text)
            if ds:
                tm = re.search(r"from\s+(\d+(?::\d+)?(?:am|pm))", h6_text, re.I)
                sales.append({"date":ds, "time":tm.group(1) if tm else "", "title":title[:80]})
                break

        if len(sales) >= 5: break

    return sales

def scrape_dates(test_limit=None):
    """Scrape dates for all houses (or first N if test_limit set)."""
    houses = load_houses()
    # Filter to EasyLive only
    houses = [h for h in houses if h.get("url") and "easyliveauction.com" in h["url"]]

    if test_limit:
        houses = houses[:test_limit]
        print(f"TEST MODE: scraping first {test_limit} houses")

    total = len(houses)
    results = {}
    with_sales = 0

    print(f"Fetching dates for {total} EasyLive houses...")

    for i, h in enumerate(houses, 1):
        name = h["name"]
        url = h["url"]
        slug = url.rstrip("/").split("/")[-1]

        print(f"[{i:>3}/{total}] {name[:50].ljust(50)}", end=" ", flush=True)

        ah = get_ah(slug)
        time.sleep(DELAY)
        if not ah:
            print("x no hash")
            results[name] = []
            continue

        sales = get_sales(ah)
        time.sleep(DELAY)
        results[name] = sales
        if sales:
            with_sales += 1
            print(f"ok {len(sales)} - next: {sales[0]['date']}")
        else:
            print("- none")

    return {
        "scraped_at": datetime.now().isoformat(),
        "houses": results,
        "summary": {"total": total, "with_sales": with_sales}
    }

def write_dates(data):
    """Write dates.json to the auction-map repo."""
    if not REPO_DIR.exists():
        print(f"ERROR: {REPO_DIR} not found.")
        sys.exit(1)

    # Drop summary before writing (not needed in the live file)
    summary = data.pop("summary", {})

    out_file = REPO_DIR / "dates.json"
    with open(out_file, "w") as f:
        json.dump(data, f, indent=2)

    print(f"\nWrote {len(data['houses'])} houses to {out_file}")
    print(f"  {summary['with_sales']}/{summary['total']} have upcoming sales")
    return out_file

def git_push():
    """Local-only convenience. On GitHub Actions the workflow commits & pushes."""
    if os.environ.get("GITHUB_ACTIONS"):
        print("Running under GitHub Actions - workflow handles commit/push.")
        return
    import subprocess
    subprocess.run(["git", "add", "dates.json"], cwd=REPO_DIR, check=True)
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=REPO_DIR,
    )
    if result.returncode == 0:
        print("No changes to dates.json - skipping commit")
        return

    commit_msg = f"Update auction dates ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
    subprocess.run(["git", "commit", "-m", commit_msg], cwd=REPO_DIR, check=True)
    subprocess.run(["git", "push"], cwd=REPO_DIR, check=True)
    print("Pushed to GitHub")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Scrape EasyLive auction dates")
    parser.add_argument("--test", type=int, metavar="N", help="Test mode: scrape only first N houses")
    parser.add_argument("--no-push", action="store_true", help="Skip git push (write file only)")
    args = parser.parse_args()

    data = scrape_dates(test_limit=args.test)
    write_dates(data)

    if not args.no_push:
        git_push()
