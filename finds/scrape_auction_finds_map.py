import os, re, json, time, hashlib, logging, requests, subprocess
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# NOTE: designed to later accept configurable search phrases (e.g. loaded from a
# config file / CLI args / repo settings). Keep ALL search-term logic flowing
# through this single list — do not hardcode "pine" anywhere else in the pipeline.
SEARCH_TERMS = ["pine"]

# Words that mark a lot as NOT antique. Matched as whole words,
# case-insensitive, against the lot title.
EXCLUDE_WORDS = [
    "new",
    "modern",
    "contemporary",
    "reproduction",
    "repro",
    "mexican",         # almost always 1990s-2000s mass-produced pine
    "ikea",
    "flatpack", "flat-pack", "flat pack",
]
_EXCLUDE_RE = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in EXCLUDE_WORDS) + r")\b", re.IGNORECASE)


def is_excluded(title):
    """Return the matched exclude word, or None if the title is fine."""
    if not title:
        return None
    m = _EXCLUDE_RE.search(title)
    return m.group(0) if m else None


# NOTE: like SEARCH_TERMS above, designed to later be configurable (edit local
# auctions from the UI/config). Keep all "is this local?" logic flowing through
# this single list. Entries are lowercase substrings matched against house names;
# "jones & jacob" / "jones and jacob" are spelling variants of ONE house (6 houses total).
LOCAL_HOUSES = [
    "churchill", "overture", "amersham",
    "bourne end", "jones & jacob", "jones and jacob", "tring market",
    "psp",
]

EASYLIVE_BASE = "https://www.easyliveauction.com"
SEARCH_URL    = f"{EASYLIVE_BASE}/catalogue/"
REPO_DIR      = Path(os.environ.get("REPO_DIR", os.path.expanduser("~/auction-finds-map")))
IMAGES_DIR    = REPO_DIR / "images"
SEEN_FILE     = REPO_DIR / "seen_lots.json"
POSTCODES_FILE = Path(os.environ.get("POSTCODES_FILE",
    REPO_DIR / "house_postcodes.json"))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

REQUEST_DELAY = 1.5
MAX_PAGES     = 30   # safety cap; pine typically returns ~16 pages
MAX_LOTS      = 200

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)


def is_local(house_name):
    name = house_name.lower()
    return any(local in name for local in LOCAL_HOUSES)


def image_filename(url):
    ext = url.split("?")[0].rsplit(".", 1)[-1]
    ext = ext if ext in ("jpg", "jpeg", "png", "webp", "gif") else "jpg"
    return hashlib.md5(url.encode()).hexdigest()[:12] + "." + ext


def download_image(url, dest):
    if dest.exists():
        return True
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            dest.write_bytes(r.content)
            return True
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
                continue
            log.warning(f"Image download failed after 3 attempts: {url}  ({e})")
            return False
    return False


def parse_card(card):
    # Image
    img_el  = card.select_one("img.lot-image")
    img_url = img_el.get("src", "") if img_el else ""
    if img_url.startswith("//"):
        img_url = "https:" + img_url
    elif img_url.startswith("/"):
        img_url = EASYLIVE_BASE + img_url

    # Link + lot ID
    link_el = card.select_one("div.grid-catalogue-thumb-container a[href]")
    href    = link_el["href"] if link_el else ""
    url     = urljoin(EASYLIVE_BASE, href) if href else ""
    lot_id  = hashlib.md5(url.encode()).hexdigest()[:12] if url else hashlib.md5(img_url.encode()).hexdigest()[:12]

    # Auction ID (shared across all lots in the same sale). It lives on a
    # child <a data-id="..."> inside the card, not on the .grid-lot div itself.
    auction_id = ""
    aid_el = card.find(attrs={"data-id": True})
    if aid_el:
        auction_id = aid_el.get("data-id", "")

    # Title — the <p> inside a.no-hover
    title_el = card.select_one("a.no-hover p")
    title    = title_el.get_text(strip=True) if title_el else ""
    if not title:
        return None

    # Estimate — find <p> containing "Estimate"
    estimate = ""
    for p in card.select("a.no-hover p"):
        txt = p.get_text(" ", strip=True)
        if "Estimate" in txt:
            estimate = txt.replace("Estimate", "").strip()
            break

    # Current bid
    bid = ""
    for p in card.select("a.no-hover p"):
        txt = p.get_text(" ", strip=True)
        if "Current Bid" in txt:
            bid = txt.replace("Current Bid:", "").strip()
            break

    # Auction house — a.blue-text inside small
    house_el = card.select_one("small a.blue-text")
    house    = house_el.get_text(strip=True).replace("by ", "") if house_el else "Unknown"

    # Time left
    time_left = ""
    small = card.select_one("small")
    if small:
        for p in small.select("p"):
            txt = p.get_text(" ", strip=True)
            if "Time Left" in txt:
                time_left = txt.replace("Time Left:", "").strip()
                break

    # Lot number - extract from URL like "...-lot-409/"
    lot_number = ""
    if url:
        lot_match = re.search(r'-lot-(\d+)/?', url)
        if lot_match:
            lot_number = lot_match.group(1)

    return {
        "id":         lot_id,
        "auction_id": auction_id,
        "title":      title,
        "house":      house,
        "estimate":   estimate,
        "bid":        bid,
        "time_left":  time_left,
        "sale_date":  "",        # populated after auction-level fetch
        "sale_dates_raw": "",    # full block, for the v2 tooltip / future per-lot parsing
        "url":        url,
        "img_url":    img_url,
        "img_file":   image_filename(img_url) if img_url else "",
        "local":     is_local(house),
        "lot_number": lot_number,
    }


def scrape_term(session, term):
    lots, seen_ids = [], set()
    excluded_total = 0
    excluded_samples = []  # (word, title) tuples for log
    for page in range(1, MAX_PAGES + 1):
        params = {"searchTerm": term, "searchOption": 3, "currentPage": page}
        try:
            r = session.get(SEARCH_URL, params=params, headers=HEADERS, timeout=20)
            if r.status_code == 404:
                log.info(f"  '{term}' page {page}: 404 (past last page) — stopping")
                break
            r.raise_for_status()
        except Exception as e:
            log.warning(f"Request failed for '{term}' page {page}: {e}")
            break

        soup  = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("div.grid-lot")

        if not cards:
            log.info(f"  No cards on '{term}' page {page} — stopping")
            break

        new = 0
        page_excluded = 0
        for card in cards:
            try:
                lot = parse_card(card)
            except Exception as e:
                log.debug(f"Parse error: {e}")
                continue
            if not lot or lot["id"] in seen_ids:
                continue
            seen_ids.add(lot["id"])
            bad = is_excluded(lot["title"])
            if bad:
                excluded_total += 1
                page_excluded += 1
                if len(excluded_samples) < 8:
                    excluded_samples.append((bad, lot["title"][:80]))
                continue
            lot["search_term"] = term
            lots.append(lot)
            new += 1

        log.info(f"  '{term}' page {page}: {len(cards)} cards, {new} kept, {page_excluded} excluded, {len(lots)} total")
        time.sleep(REQUEST_DELAY)
        if len(cards) < 10:
            break

    if excluded_total:
        log.info(f"  '{term}' excluded {excluded_total} lots by EXCLUDE_WORDS; samples:")
        for word, title in excluded_samples:
            log.info(f"    [{word}] {title}")

    return lots


# --- Seen-lots tracking ---------------------------------------------------
def load_seen():
    """Return set of lot IDs we've seen in previous runs."""
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()))
        except Exception:
            return set()
    return set()


def save_seen(lot_ids):
    SEEN_FILE.write_text(json.dumps(sorted(lot_ids)), encoding="utf-8")


# --- House postcode lookup / fuzzy matching -------------------------------
_COMPANY_SUFFIXES = [
    " ltd", " limited", " llp", " plc",
    " and valuers", " & valuers",
]


def _normalize(name):
    n = (name or "").strip().lower()
    n = n.rstrip(".,;:·- ")
    changed = True
    while changed:
        changed = False
        for suf in _COMPANY_SUFFIXES:
            if n.endswith(suf):
                candidate = n[: -len(suf)].strip()
                if len(candidate.split()) >= 2:
                    n = candidate
                    changed = True
    return n


def load_postcodes():
    if not POSTCODES_FILE.exists():
        return {}, {}
    try:
        data = json.loads(POSTCODES_FILE.read_text())
    except Exception:
        return {}, {}
    raw = {k: v for k, v in data.items() if not k.startswith("_")}
    norm = {}
    for name, info in raw.items():
        key = _normalize(name)
        if key and key not in norm:
            norm[key] = info
    return raw, norm


def _find_truncated(name, raw):
    if not name or not name.endswith("..."):
        return None
    stem = name[:-3].strip().lower()
    if len(stem) < 6:
        return None
    matches = [info for full, info in raw.items() if full.lower().startswith(stem)]
    if len(matches) == 1:
        return matches[0]
    nstem = _normalize(name)
    if nstem and len(nstem) >= 6:
        nmatches = [info for full, info in raw.items() if _normalize(full).startswith(nstem)]
        if len(nmatches) == 1:
            return nmatches[0]
        rev = [info for full, info in raw.items() if nstem.startswith(_normalize(full)) and len(_normalize(full)) >= 6]
        if len(rev) == 1:
            return rev[0]
    return None


def house_meta(house, postcodes):
    raw, norm = postcodes
    info = (
        raw.get(house)
        or norm.get(_normalize(house))
        or _find_truncated(house, raw)
    )
    if not info:
        return {"postcode": None, "location": None, "map_url": None, "known": False}
    pc = info.get("postcode", "")
    loc = info.get("location") or ""
    if not loc and info.get("address"):
        addr = info["address"]
        if pc and pc in addr:
            addr = addr.replace(pc, "").strip().rstrip(",")
        loc = addr
    map_url = f"https://www.google.com/maps/search/?api=1&query={pc.replace(' ', '+')}" if pc else None
    easylive_url = info.get("url") or None
    return {"postcode": pc, "location": loc, "map_url": map_url, "easylive_url": easylive_url, "known": True}


# --- HTML rendering -------------------------------------------------------
def _today_date_str(d=None):
    """Return EasyLive's date format for `d` (default today), e.g.
    'Sun 24th May 2026'. Used to match against `sale_date` / `sale_dates_raw`.
    """
    from datetime import date as _date
    d = d or _date.today()
    DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d.weekday()]
    def _suffix(n):
        if 10 <= n % 100 <= 20: return "th"
        return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{DOW} {d.day}{_suffix(d.day)} {d.strftime('%b')} {d.year}"


def _is_today(lot, today_str):
    """True if the lot's sale_date or sale_dates_raw mentions today.
    Matches both 'Ends Sun 24th May 2026 ...' (timed) and multi-day live
    bands like 'Sun 24th May 2026 9am BST (Lots 1 to 765) Mon 25th ...'.
    """
    blob = (lot.get("sale_date") or "") + " || " + (lot.get("sale_dates_raw") or "")
    return today_str in blob


def _card_html(lot, is_new, postcodes):
    img_src = f"images/{lot['img_file']}" if lot.get("img_file") else ""
    img_tag = (
        f'<img src="{img_src}" alt="{lot["title"]}" width="400" height="300" loading="lazy">'
        if img_src else '<div class="no-img">No image</div>'
    )
    bid      = f'<span class="bid">Bid {lot["bid"]}</span>'           if lot.get("bid")       else ""
    estimate = f'<span class="estimate">Est {lot["estimate"]}</span>' if lot.get("estimate") else ""

    sale_date = lot.get("sale_date") or ""
    sale_raw  = (lot.get("sale_dates_raw") or "").replace('"', "'")
    if sale_date:
        tip = f' data-tip="📅 {sale_raw}"' if sale_raw and sale_raw != sale_date else ''
        saledate_html = f'<span class="saledate"{tip}>📅 {sale_date}</span>'
    elif lot.get("time_left"):
        saledate_html = f'<span class="timeleft">⏱ {lot["time_left"]}</span>'
    else:
        saledate_html = ""
    new_badge = '<span class="new-badge">NEW</span>' if is_new else ""

    h = house_meta(lot.get("house", ""), postcodes)
    if h["known"] and (h["easylive_url"] or h["map_url"]):
        link = h["easylive_url"] or h["map_url"]
        dest_label = "EasyLive" if h["easylive_url"] else "map"
        tooltip = f'📍 {h["postcode"]}'
        if h["location"]:
            tooltip += f' · {h["location"]}'
        tooltip += f' · click for {dest_label}'
        house_html_str = (
            f'<span class="house" data-tip="{tooltip}" '
            f'onclick="event.preventDefault(); event.stopPropagation(); '
            f"window.open('{link}','_blank'); "
            f'">{lot["house"]} <span class="pc">{h["postcode"]}</span></span>'
        )
    elif h["known"]:
        loc = h["location"] or "location on file"
        house_html_str = f'<span class="house" data-tip="🌍 {loc}">{lot["house"]} <span class="pc pc-intl">{loc}</span></span>'
    else:
        house_html_str = f'<span class="house unknown" data-tip="📍 postcode unknown">{lot["house"]} <span class="pc-unknown">?</span></span>'

    lot_num_html = f'<span class="lot-number">Lot {lot["lot_number"]}</span>' if lot.get("lot_number") else ""

    return f"""
    <a class="card" href="{lot['url']}" target="_blank" rel="noopener">
      <div class="card-img">{img_tag}{new_badge}</div>
      <div class="card-body">
        <p class="title">{lot['title']}</p>
        <p class="house-line">{house_html_str}</p>
        <div class="meta">{lot_num_html}{bid}{estimate}{saledate_html}</div>
      </div>
    </a>"""


def _section_html(title, lots, anchor, seen, postcodes, css_class=""):
    if not lots:
        return f'<section id="{anchor}" class="{css_class}"><h2>{title}</h2><p class="empty">No results found.</p></section>'
    cards = "\n".join(_card_html(l, l["id"] not in seen, postcodes) for l in lots)
    new_count = sum(1 for l in lots if l["id"] not in seen)
    new_pill = f' <span class="new-count">{new_count} new</span>' if new_count else ""
    return f"""
    <section id="{anchor}" class="{css_class}">
      <h2>{title} <span class="count">{len(lots)} lots</span>{new_pill} <span class="progress" data-total="{len(lots)}"></span></h2>
      <div class="masonry">{cards}</div>
    </section>"""


# ── PRIVATE DEMO LOGIN GATE ──────────────────────────────────────────
# Plain string (NOT an f-string) so its CSS/JS braces need no escaping.
# Injected into the page template via {gate_html}. Keep in sync with houses/index.html.
DEMO_GATE_HTML = """<!-- ── PRIVATE DEMO LOGIN GATE ─────────────────────────────────────────
     This app is a private demonstration. It is NOT open to the public.
     Client-side gate: password is checked as a SHA-256 hash and access
     lasts for the browser session only. To change the password, run:
       echo -n "NewPassword" | shasum -a 256
     and replace GATE_HASH below (in BOTH houses/ and finds/, and in the
     finds scraper template). -->
<div id="demo-gate">
  <div id="demo-gate-card">
    <img src="logo.png" alt="Auction Hunter" style="height:48px;width:auto;margin-bottom:14px">
    <h2>Auction Hunter</h2>
    <p class="dg-sub">🔒 Private demonstration — not open to the public.<br>Access is by invitation only.</p>
    <form id="demo-gate-form">
      <input type="password" id="demo-gate-pw" placeholder="Password" autocomplete="current-password" autofocus>
      <button type="submit">Enter demo</button>
    </form>
    <p class="dg-err" id="demo-gate-err"></p>
  </div>
</div>
<style>
#demo-gate{position:fixed;inset:0;z-index:99999;background:#f9fafb;display:flex;align-items:center;justify-content:center;font-family:'DM Sans',sans-serif}
#demo-gate-card{background:#fff;border:1px solid #ecedf0;border-radius:14px;box-shadow:0 8px 30px rgba(20,30,40,.08);padding:38px 40px;text-align:center;max-width:340px;width:90%}
#demo-gate-card h2{font-family:'Playfair Display',serif;font-size:1.3rem;color:#111827;margin:0 0 6px}
#demo-gate-card .dg-sub{font-size:.8rem;color:#6b7280;line-height:1.5;margin:0 0 18px}
#demo-gate-pw{width:100%;padding:10px 14px;border:1px solid #d1d5db;border-radius:8px;font-size:.9rem;font-family:inherit;outline:none;margin-bottom:10px;box-sizing:border-box}
#demo-gate-pw:focus{border-color:#3a5c3b}
#demo-gate-form button{width:100%;padding:10px 14px;border:none;border-radius:20px;background:#3a5c3b;color:#fff;font-size:.85rem;font-weight:600;font-family:inherit;cursor:pointer}
#demo-gate-form button:hover{background:#2c4a2d}
.dg-err{font-size:.75rem;color:#b91c1c;min-height:1em;margin:10px 0 0}
body.gate-locked{overflow:hidden}
</style>
<script>
(function(){
  var GATE_HASH='3b39de0bbf51af9461938056432a535491f2659be786b4b6cd68c828407a1b26';
  var KEY='ah_demo_ok';
  function unlock(){var g=document.getElementById('demo-gate');if(g)g.remove();document.body.classList.remove('gate-locked');}
  if(localStorage.getItem(KEY)===GATE_HASH){unlock();return;}
  document.body.classList.add('gate-locked');
  async function sha256(s){var b=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s));return Array.from(new Uint8Array(b)).map(function(x){return x.toString(16).padStart(2,'0')}).join('');}
  document.getElementById('demo-gate-form').addEventListener('submit',async function(e){
    e.preventDefault();
    var pw=document.getElementById('demo-gate-pw').value;
    var h=await sha256(pw);
    if(h===GATE_HASH){localStorage.setItem(KEY,h);unlock();}
    else{document.getElementById('demo-gate-err').textContent='Incorrect password.';document.getElementById('demo-gate-pw').value='';}
  });
})();
</script>
"""


def build_html(local_lots, wide_lots, seen=None, postcodes=None):
    """Generate the combined auction-finds + map HTML."""
    if seen is None:
        seen = set()
    if postcodes is None:
        postcodes = ({}, {})
    now       = datetime.now().strftime("%A %d %B, %H:%M")
    gate_html = DEMO_GATE_HTML
    terms_str = ", ".join(SEARCH_TERMS)
    total     = len(local_lots) + len(wide_lots)
    new_total = sum(1 for l in local_lots + wide_lots if l["id"] not in seen)

    today_str = _today_date_str()
    local_today = [l for l in local_lots if _is_today(l, today_str)]
    local_later = [l for l in local_lots if not _is_today(l, today_str)]
    wide_today  = [l for l in wide_lots  if _is_today(l, today_str)]
    wide_later  = [l for l in wide_lots  if not _is_today(l, today_str)]
    today_total = len(local_today) + len(wide_today)

    # Build PC_MAP from postcodes data (only houses with lat/lng)
    raw_pc, _ = postcodes
    pc_entries = []
    for name, info in raw_pc.items():
        if not isinstance(info, dict):
            continue
        pc = info.get("postcode", "")
        lat = info.get("lat")
        lng = info.get("lng")
        url = info.get("url", "")
        if pc and lat and lng:
            pc_key = pc.replace(" ", "").upper()
            n_esc = info["name"] if "name" in info else name
            n_esc = json.dumps(n_esc)
            u_esc = json.dumps(url)
            pc_entries.append(f'  "{pc_key}":{{name:{n_esc},lat:{lat},lng:{lng},url:{u_esc}}}')
    pc_map_js = "const PC_MAP = {\n" + ",\n".join(pc_entries) + "\n};"

    # Render card sections
    local_html = _section_html("📍 Local auctions", local_lots, "local", seen, postcodes, "local-section")
    today_html = _section_html(f"🔥 UK-Wide · selling today ({today_str})", wide_today, "today", seen, postcodes, "today-section") if wide_today else ""
    later_html = _section_html("🇬🇧 UK-Wide · later", wide_later, "uk-wide", seen, postcodes, "later-section")

    local_local_count = len(local_lots)
    wide_today_count = len(wide_today)
    wide_later_count = len(wide_later)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Auction Hunter — Auction Finds</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    :root {{
      /* Shared design tokens — extracted from Auction Hunter (/houses) */
      --bg: #f9fafb;
      --panel: #ffffff;
      --ink: #1a1a18;
      --muted: #6b7280;
      --accent: #3a5c3b;      /* AH --pine */
      --accent-soft: #e9ece9;
      --line: #ecedf0;        /* AH --line */
      --chip-bg: #f3f4f6;     /* AH .chip base */
      --chip-ink: #4b5563;
      --local-bg: #f1f5f1;
      --local-border: #3a5c3b;
      --later-bg: #f6f5f2;
      --later-border: #a8a196;
      --shadow: 0 1px 3px rgba(20,30,40,0.05), 0 4px 12px rgba(20,30,40,0.05);
      --shadow-hover: 0 4px 10px rgba(20,30,40,0.09), 0 10px 28px rgba(20,30,40,0.10);
      --radius: 10px;
      --new-bg: #3a5c3b;
      --highlight: #4b6b8a;
    }}

    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{ background: var(--bg); color: var(--ink); height: 100%; }}
    body {{
      font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      -webkit-font-smoothing: antialiased;
      display: flex;
      flex-direction: column;
    }}

    header {{
      background: var(--panel);
      border-bottom: 1px solid var(--line);
      padding: 8px 24px;
      position: sticky; top: 0; z-index: 1000;
      backdrop-filter: blur(8px);
      display: flex; align-items: center; gap: 8px 18px; flex-wrap: wrap;
    }}
    /* Tagline shown on desktop, matching Houses — hidden only on mobile
       (see the mobile media query below) to keep the phone header compact. */
    header .tagline {{ font-size: .78rem; color: #6b7280; margin: 2px 0 0; max-width: 480px; line-height: 1.3; }}
    .hstatus {{ display: flex; align-items: center; gap: 6px 14px; flex-wrap: wrap; }}
    /* headtop holds ONLY brand + toggle — identical markup on both Finds and
       Houses. It always claims its own full-width line (flex-basis:100%),
       so its layout depends purely on viewport width, never on how long the
       page-specific status text below happens to be. That's what guarantees
       the toggle lands in the same place on both pages. */
    .headtop {{ display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; }}
    .update-ok {{ font-size: .78rem; color: #22c55e; font-weight: 600; display: flex; align-items: center; gap: 4px; white-space: nowrap; }}
    .hstats {{ font-size: .78rem; color: var(--muted); white-space: nowrap; }}
    .hstats strong {{ color: var(--ink); }}
    .hrow2 {{ flex-basis: 100%; display: flex; align-items: center; gap: 8px 12px; flex-wrap: wrap; }}
    .term-tag {{
      font-size: 0.74rem; color: var(--accent); font-weight: 600;
      background: var(--accent-soft); border: 1px solid var(--accent);
      padding: 5px 12px; border-radius: 20px; white-space: nowrap;
    }}
    .term-tag .term-soon {{ color: var(--muted); font-weight: 400; }}
    @media (max-width: 700px) {{ .term-tag .term-soon {{ display: none; }} }}
    header nav.jump {{ flex-basis: auto; margin: 0; padding: 0; }}
    .brand {{ display: flex; align-items: center; gap: 10px; }}
    .demo-tag {{ font-size: .62rem; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; color: #92400e; background: #fef3c7; border: 1px solid #fcd34d; padding: 3px 9px; border-radius: 20px; white-space: nowrap; }}
    .brand h1 {{ font-family: 'Playfair Display', serif; font-size: 1.25rem; font-weight: 700; letter-spacing: -0.01em; color: #111827; white-space: nowrap; }}
    .brand .logo {{ font-size: 1.5rem; }}
    .meta {{ font-size: 0.78rem; color: var(--muted); margin-left: auto; }}
    .meta strong {{ color: var(--ink); }}
    .search-box {{
      flex: 1;
      min-width: 200px;
      max-width: 400px;
      position: relative;
    }}
    .search-box input {{
      width: 100%;
      padding: 8px 36px 8px 12px;
      border: 1px solid var(--accent-soft);
      border-radius: 8px;
      background: var(--panel);
      color: var(--ink);
      font-size: 0.85rem;
      font-family: inherit;
      outline: none;
    }}
    .search-box input:focus {{ border-color: var(--accent); }}
    .search-box .clear-btn {{
      display: none;
      position: absolute; right: 6px; top: 50%; transform: translateY(-50%);
      background: var(--accent-soft); border: none;
      font-size: 0.7rem; cursor: pointer;
      width: 20px; height: 20px; border-radius: 50%;
      align-items: center; justify-content: center; color: var(--muted);
    }}
    .search-box.has-text .clear-btn {{ display: flex; }}
    .search-results {{ font-size: 0.78rem; color: var(--muted); }}
    /* Shared app nav (Houses ↔ Finds) — mirrors AH .tbtn pill style */
    /* Segmented page toggle: one control, split in two, so the two-page
       structure (Houses ↔ Finds) reads instantly and stands apart from links. */
    .app-nav {{
      display: inline-flex; padding: 3px; gap: 0;
      background: var(--accent-soft); border: 1px solid var(--accent);
      border-radius: 22px;
    }}
    .app-nav-link {{
      font-size: 0.82rem; font-weight: 700; padding: 7px 18px;
      border-radius: 18px; border: 0; background: transparent;
      color: var(--accent); letter-spacing: -0.01em;
      text-decoration: none; white-space: nowrap; transition: all .18s;
      display: inline-flex; align-items: center; gap: 5px;
    }}
    .app-nav-link:hover {{ color: #fff; background: rgba(58,92,59,.55); }}
    .app-nav-link.on {{
      background: var(--accent); color: #fff;
      box-shadow: 0 1px 4px rgba(58,92,59,.35);
    }}
    .app-nav-link.on:hover {{ background: var(--accent); }}
    nav.jump {{ display: flex; gap: 6px; flex-wrap: wrap; }}
    nav.jump a {{
      font-size: 0.7rem;
      padding: 6px 14px;
      background: var(--chip-bg);   /* AH .chip base */
      border-radius: 20px;
      color: var(--chip-ink);
      text-decoration: none;
      font-weight: 500;
      transition: 0.15s;
      /* Promote each pill to its own GPU compositor layer. On mobile the header
         (and these buttons) scroll off-screen; Chrome-on-Samsung was re-painting
         them with STALE pixels when they scrolled back into view during a fast
         momentum scroll — so a button looked green even though its .active class
         had already been removed (confirmed: debug showed correct active state,
         wrong colour on screen). Own-layer promotion forces a correct
         re-composite on re-entry. translateZ(0)+backface-visibility is the
         standard remedy. */
      transform: translateZ(0);
      -webkit-transform: translateZ(0);
      backface-visibility: hidden;
      -webkit-backface-visibility: hidden;
    }}
    /* Hover only on real pointer devices — on touchscreens :hover "sticks" to
       the tapped button until you tap elsewhere, which looked like the active
       indicator was stuck on. Guarding with (hover:hover) stops that. */
    @media (hover: hover) {{
      nav.jump a:hover {{ background: var(--accent); color: var(--panel); }}
    }}
    /* Active = the section currently in view (scrollspy) or just clicked.
       One green at a time; overrides hover so it stays lit. */
    nav.jump a.active {{ background: var(--accent); color: var(--panel); }}
    .new-badge {{
      position: absolute; top: 10px; left: 10px;
      background: var(--new-bg); color: #fff;
      font-size: 0.65rem; font-weight: 800;
      padding: 4px 8px; border-radius: 4px;
      letter-spacing: 0.06em;
      box-shadow: 0 2px 6px rgba(0,0,0,0.2);
    }}
    footer {{
      text-align: center;
      font-size: 0.8rem;
      color: var(--muted);
      padding: 32px 24px 24px;
      border-top: 1px solid var(--accent-soft);
    }}
    footer a {{ color: var(--accent); text-decoration: none; }}

    #main-layout {{
      display: flex;
      flex: 1;
      min-height: 0;
    }}
    #map-panel {{
      width: 320px;
      min-width: 320px;
      position: relative;
      border-right: 1px solid var(--accent-soft);
      flex-shrink: 0;
    }}
    #map-panel #map {{ width: 100%; height: 100%; }}
    #map-panel .map-label {{
      position: absolute;
      top: 8px; left: 50%;
      transform: translateX(-50%);
      z-index: 1000;
      background: rgba(0,0,0,0.6);
      color: #fff;
      font-size: 0.7rem;
      padding: 5px 14px;
      border-radius: 8px;
      pointer-events: none;
      white-space: nowrap;
      text-align: center;
    }}
    #cards-area {{
      flex: 1;
      overflow-y: auto;
      padding: 0 24px 40px;
    }}
    #cards-area section {{
      max-width: 1400px;
      margin: 36px auto 0;
      padding: 0;
    }}
    #cards-area section.local-section {{
      background: var(--local-bg);
      border-left: 4px solid var(--local-border);
      padding: 28px 24px 32px;
      border-radius: var(--radius);
      margin: 36px 0 0;
    }}
    #cards-area section.today-section {{
      background: linear-gradient(180deg, rgba(75, 107, 138, 0.08), rgba(75, 107, 138, 0.02));
      border-left: 4px solid var(--highlight);
      padding: 28px 24px 32px;
      border-radius: var(--radius);
      margin: 36px 0 0;
    }}
    #cards-area section.later-section {{
      background: var(--later-bg);
      border-left: 4px solid var(--later-border);
      padding: 28px 24px 32px;
      border-radius: var(--radius);
      margin: 36px 0 0;
    }}
    /* Sticky per-section headers: as the user scrolls through a section it
       stays pinned just under the main header, so which group (Local/Today/
       Later) they're browsing is always visible. #cards-area is the scroll
       container, so top:0 here means "flush against the app header." */
    #cards-area section h2 {{
      font-family: 'Playfair Display', serif;
      font-size: 1.1rem;
      margin-bottom: 18px;
      font-weight: 700;
      position: sticky;
      top: 0;
      z-index: 5;
      padding: 10px 0;
      margin: 0 -24px 8px;
      padding-left: 24px;
      padding-right: 24px;
    }}
    #cards-area section.local-section h2 {{ background: var(--local-bg); }}
    #cards-area section.today-section h2 {{ background: #eef2f6; }}
    #cards-area section.later-section h2 {{ background: var(--later-bg); }}
    #cards-area section h2 .count {{
      font-size: 0.82rem;
      font-weight: 500;
      color: var(--muted);
    }}
    #cards-area section h2 .progress {{
      font-size: 0.74rem;
      font-weight: 500;
      color: var(--muted);
      font-family: 'DM Sans', sans-serif;
      float: right;
    }}
    #back-to-top {{
      position: fixed; left: 16px; bottom: 16px; z-index: 1400;
      background: var(--accent); color: #fff;
      border: none; border-radius: 999px;
      width: 44px; height: 44px;
      font-size: 1.1rem; cursor: pointer;
      box-shadow: 0 4px 16px rgba(40,30,15,0.28);
      display: flex; align-items: center; justify-content: center;
      opacity: 0; pointer-events: none;
      transform: translateY(8px);
      transition: opacity .18s ease, transform .18s ease;
    }}
    #back-to-top.visible {{ opacity: 1; pointer-events: auto; transform: translateY(0); }}
    /* CSS Grid (not multicolumn masonry) so every card sits in a clean,
       aligned row and all cards are the same height. */
    .masonry {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; align-items: start; }}
    @media (max-width: 1000px) {{ .masonry {{ grid-template-columns: repeat(2, 1fr); }} }}
    @media (max-width: 600px)  {{ .masonry {{ grid-template-columns: 1fr; }} }}
    .card {{
      display: flex; flex-direction: column; width: 100%;
      background: var(--panel);
      border-radius: var(--radius);
      overflow: hidden;
      text-decoration: none; color: inherit;
      box-shadow: var(--shadow);
      transition: transform 0.18s ease, box-shadow 0.18s ease;
    }}
    .card:hover {{ transform: translateY(-3px); box-shadow: var(--shadow-hover); }}
    .card-img {{ position: relative; width: 100%; line-height: 0; background: var(--accent-soft); }}
    /* Uniform SQUARE image crop for a tidy catalogue look. height:auto is
       essential — the <img> tags carry a height="300" HTML attribute that
       otherwise overrides aspect-ratio, making cards render at different
       shapes depending on their column width (3-col local vs 4-col later). */
    .card-img img {{ width: 100%; height: auto; aspect-ratio: 1/1; object-fit: cover; display: block; }}
    .no-img {{
      aspect-ratio: 1/1; display: flex; align-items: center;
      justify-content: center; font-size: 0.8rem; color: var(--muted);
    }}
    .card-body {{ padding: 12px 14px 14px; }}
    .card-body .title {{
      font-size: 0.82rem; font-weight: 600;
      line-height: 1.4; margin-bottom: 6px;
      display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
      overflow: hidden;
      /* Reserve exactly 3 lines so every card body is the same height,
         keeping grid rows perfectly aligned regardless of title length. */
      height: calc(3 * 1.4em);
    }}
    .house-line {{ font-size: 0.74rem; color: var(--muted); line-height: 1.3; }}
    .house {{
      position: relative; cursor: pointer;
      border-bottom: 1px dotted var(--muted);
    }}
    .house:hover {{ color: var(--accent); border-bottom-color: var(--accent); }}
    .house.highlighted {{ color: var(--highlight); border-bottom-color: var(--highlight); }}
    .house.unknown {{ opacity: 0.7; }}
    .pc {{
      display: inline-block; margin-left: 4px;
      background: var(--accent-soft); color: var(--accent);
      padding: 1px 6px; border-radius: 4px;
      font-size: 0.65rem; font-weight: 600;
    }}
    .card-body .meta {{
      display: flex; align-items: center;
      gap: 10px; margin-top: 6px;
      font-size: 0.72rem;
      flex-wrap: nowrap; overflow: hidden; white-space: nowrap;
    }}
    .lot-number {{
      background: var(--ink); color: var(--panel);
      padding: 1px 8px; border-radius: 4px;
      font-weight: 600; font-size: 0.65rem;
      flex-shrink: 0;
    }}
    .estimate {{ font-weight: 600; color: var(--accent); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .saledate {{ color: var(--muted); flex-shrink: 0; margin-left: auto; }}

    /* ── MAP PIN STYLES ── */
    .pin-default {{
      width: 8px; height: 8px;
      background: transparent;
      border: none;
      border-radius: 50%;
      opacity: 0;
      transition: all 0.2s;
    }}
    .pin-highlighted {{
      width: 16px; height: 16px;
      background: #d9531e;
      border: 3px solid #fff;
      border-radius: 50%;
      box-shadow: 0 0 12px rgba(217,83,30,.6);
    }}
    /* Timing colour bands (mirror Auction Hunter): now / this week / later / no date */
    .pin-now    {{ background: #2c6e2c !important; box-shadow: 0 0 12px rgba(44,110,44,.65) !important; }}
    .pin-week   {{ background: #e0b000 !important; box-shadow: 0 0 12px rgba(224,176,0,.6) !important; }}
    .pin-later  {{ background: #b5651d !important; box-shadow: 0 0 12px rgba(181,101,29,.6) !important; }}
    .pin-none   {{ background: #8a8a8a !important; box-shadow: 0 0 12px rgba(138,138,138,.55) !important; }}

    /* ── MOBILE MAP OVERLAY ── */
    #map-fab {{
      display: none;
      position: fixed; right: 16px; bottom: 16px; z-index: 1500;
      background: var(--accent); color: #fff;
      border: none; border-radius: 999px;
      padding: 13px 20px; font-size: 0.9rem; font-weight: 700;
      font-family: inherit; cursor: pointer;
      box-shadow: 0 4px 16px rgba(40,30,15,0.28);
    }}
    #map-close {{
      display: none;
      position: absolute; right: 12px; top: 12px; z-index: 1600;
      background: rgba(0,0,0,0.7); color: #fff;
      border: none; border-radius: 999px;
      padding: 9px 18px; font-size: 0.85rem; font-weight: 700;
      font-family: inherit; cursor: pointer;
    }}

    @media (max-width: 800px) {{
      /* ── COMPACT MOBILE HEADER ──
         Header un-sticks (scrolls away with content) and shrinks hard so
         the lots get the screen. Also kills sideways scroll: nowrap items
         are allowed to wrap, pill rows become horizontal swipers. */
      html, body {{ overflow-x: hidden; }}
      header {{
        position: static;             /* scrolls away — frees the whole screen */
        padding: 8px 12px 8px;
        gap: 6px 10px;
      }}
      header .tagline {{ display: none; }}
      .headtop {{ flex-basis: 100%; }}
      .brand img {{ height: 22px !important; }}
      .brand {{ gap: 5px; }}
      .brand h1 {{ font-size: 0.88rem; }}
      .brand a {{ font-size: .64rem !important; margin-left: 0 !important; }}
      .demo-tag {{ font-size: .52rem; padding: 2px 7px; }}
      .hstatus {{ flex-basis: 100%; gap: 4px 8px; }}
      .update-ok {{ white-space: normal; font-size: .68rem; }}
      .hstats {{ white-space: normal; font-size: .68rem; }}
      .app-nav {{ padding: 2px; }}
      .app-nav-link {{ font-size: .64rem; padding: 4px 9px; }}
      .hrow2 {{ gap: 6px 8px; }}
      .search-box {{ min-width: 0; flex-basis: 100%; max-width: none; }}
      .term-tag {{ font-size: .6rem; padding: 3px 9px; }}
      nav.jump {{
        margin-left: 0; flex-basis: 100%;
        flex-wrap: nowrap; overflow-x: auto;   /* one swipeable row */
        -webkit-overflow-scrolling: touch;
        scrollbar-width: none;
        gap: 5px;                              /* tighter so all 4 fit */
      }}
      nav.jump::-webkit-scrollbar {{ display: none; }}
      nav.jump a {{ flex-shrink: 0; font-size: 0.62rem; padding: 5px 9px; }}

      #map-panel {{ display: none; }}
      #cards-area {{ padding: 0 12px 24px; }}
      /* No standalone map on mobile (Ken's call): a cold map with no pin lit
         answers nothing. Map entrance will be tap-item -> pin (planned).
         Footer also hidden on mobile to give listings the room. */
      #map-fab {{ display: none; }}
      footer {{ display: none; }}
      body.map-open #map-panel {{
        display: block;
        position: fixed; inset: 0; z-index: 1550;
        width: 100%; min-width: 0; border-right: none;
      }}
      body.map-open #map-close {{ display: block; }}
      body.map-open #map-fab {{ display: none; }}
    }}
  </style>
</head>
<body>
{gate_html}
  <header>
    <div class="headtop">
      <div class="brand"><img src="logo.png" alt="Auction Hunter" style="height:40px;width:auto"><h1>Auction Hunter</h1><a href="../about.html" style="font-size:.78rem;color:#6b7280;text-decoration:none;margin-left:2px">About</a></div>
      <nav class="app-nav" aria-label="App pages">
        <a href="../houses/" class="app-nav-link">Map</a>
        <a href="../finds/" class="app-nav-link on">Lots</a>
      </nav>
    </div>
    <p class="tagline">Fresh pine finds from auction houses across the UK — click any lot to see it and bid</p>
    <div class="hstatus">
      <span class="update-ok">✅ Successfully updated - {now}</span>
      <span class="hstats"><strong>{total} lots</strong> · {today_total} today · {new_total} new since yesterday</span>
    </div>
    <div class="hrow2">
      <div class="search-box" id="searchBox">
        <input type="text" id="searchInput" placeholder="🔍 Search items below (e.g. bedside cupboard, chest of drawers...)" oninput="searchItems()">
        <button class="clear-btn" onclick="clearSearch()" title="Clear search">✕</button>
      </div>
      <span class="search-results" id="searchResults"></span>
      <nav class="jump" aria-label="Jump to section">
        <a href="#local" data-target="local">Local · {local_local_count}</a>
        {f'<a href="#today" data-target="today">UK Today · {wide_today_count}</a>' if wide_today_count else ''}
        <a href="#uk-wide" data-target="uk-wide">UK Later · {wide_later_count}</a>
      </nav>
    </div>
  </header>

  <div id="main-layout">
    <div id="map-panel">
      <button id="map-close" onclick="closeMobileMap()">✕ Close map</button>
      <div id="map"></div>
      <div class="map-label">Hover name for map location</div>
    </div>
    <div id="cards-area">
      {local_html}
      {today_html}
      {later_html}
    </div>
  </div>

  <button id="map-fab" onclick="openMobileMap()">🗺 Map</button>
  <button id="back-to-top" onclick="scrollCardsToTop()" aria-label="Back to top" title="Back to top">↑</button>

  <footer>
    Auction Hunter · lots refreshed daily from EasyLive
  </footer>

  <script>
{pc_map_js}

    // ── SEARCH ──

    // ── SECTION NAV (scrollspy) ──
    // Three buttons (Local / UK Today / UK Later) are pure navigation +
    // position indicator — NOT filters. Click = smooth-scroll to that bunch;
    // the button for whichever bunch is currently in view goes green on its
    // own as you scroll. #cards-area is the scroll container on desktop; on
    // mobile the window scrolls — detect whichever actually overflows.
    function jumpScroller() {{
      const ca = document.getElementById('cards-area');
      if (ca && ca.scrollHeight > ca.clientHeight + 2) return ca;
      return document.scrollingElement || document.documentElement;
    }}
    function jumpSections() {{
      return ['local', 'today', 'uk-wide']
        .map(id => document.getElementById(id))
        .filter(Boolean);
    }}
    function jumpLinks() {{ return document.querySelectorAll('nav.jump a[data-target]'); }}
    var jumpActiveId = null;
    function setActiveJump(id) {{
      if (id === jumpActiveId) return;   // no change → nothing to repaint
      jumpActiveId = id;
      jumpLinks().forEach(a => {{
        const on = a.dataset.target === id;
        a.classList.toggle('active', on);
        // Force Chrome-on-Samsung to actually re-paint the pill. Own-layer
        // promotion (translateZ in CSS) handles most cases, but nudging the
        // layer with a tiny transform toggle guarantees the stale-green pixels
        // are discarded when the header scrolls back into view after a fling.
        a.style.transform = on ? 'translateZ(0) scale(1.0001)' : 'translateZ(0)';
      }});
    }}
    function scrollToSection(id) {{
      const sc = jumpScroller();
      // Local is the first bunch / default view → go right to the very top.
      if (id === 'local') {{
        sc.scrollTo({{ top: 0, behavior: 'smooth' }});
        return;
      }}
      const sec = document.getElementById(id);
      if (!sec) return;
      const scRect = (sc === document.scrollingElement || sc === document.documentElement)
        ? {{ top: 0 }} : sc.getBoundingClientRect();
      const delta = sec.getBoundingClientRect().top - scRect.top;
      // Align the section (and its sticky heading) flush to the top of the
      // scroll viewport; the app header sits outside #cards-area so nothing
      // is hidden underneath it. Small -8px breathing gap.
      sc.scrollTo({{ top: sc.scrollTop + delta - 8, behavior: 'smooth' }});
    }}
    // Debug overlay (only when URL has ?debug=1) — prints live scrollspy numbers
    // so we can diagnose device-specific behaviour (e.g. Chrome-on-Samsung)
    // without guessing. Reports each section heading's viewport-top, the
    // detection line, and which button is active.
    var JUMP_DEBUG = /[?&]debug=1/.test(location.search);
    var jumpDbgEl = null;
    function jumpDebug() {{
      if (!JUMP_DEBUG) return;
      if (!jumpDbgEl) {{
        jumpDbgEl = document.createElement('div');
        jumpDbgEl.style.cssText = 'position:fixed;left:4px;bottom:4px;z-index:99998;background:rgba(0,0,0,.85);color:#0f0;font:11px/1.35 monospace;padding:6px 8px;border-radius:6px;max-width:60vw;pointer-events:none;white-space:pre';
        document.body.appendChild(jumpDbgEl);
      }}
      const line = Math.max(120, (window.innerHeight || 600) * 0.4);
      const rows = jumpSections().map(s => s.id.padEnd(8) + Math.round(s.getBoundingClientRect().top));
      const act = [...document.querySelectorAll('nav.jump a.active')].map(a => a.dataset.target).join(',') || '(none)';
      jumpDbgEl.textContent =
        'line=' + Math.round(line) + '  vh=' + (window.innerHeight||0) + '\\n' +
        rows.join('\\n') + '\\n' +
        'active=' + act;
    }}

    // Active-section detection via IntersectionObserver. The browser computes
    // intersections in its own compositor, independent of JS timing, so this is
    // immune to the stale getBoundingClientRect readings Chrome-on-Samsung
    // returns during a fast fling/momentum scroll — which is why rect-polling
    // stuck intermittently on FAST scroll but always worked on SLOW scroll.
    // This is the standard, reliable scrollspy.
    var jumpVisible = {{}};
    function recomputeActive() {{
      const secs = jumpSections();
      if (!secs.length) return;
      // current = the LAST section (in page order) currently crossing the
      // top-40% detection band; fall back to the first if none are.
      let current = secs[0].id;
      secs.forEach(sec => {{ if (jumpVisible[sec.id]) current = sec.id; }});
      setActiveJump(current);
    }}
    function initJumpObserver() {{
      const secs = jumpSections();
      if (!secs.length || !('IntersectionObserver' in window)) {{ updateJumpSpy(); return; }}
      // root:null = observe each section relative to the actual SCREEN/viewport,
      // NOT a specific scroll container. This is the crucial fix: on desktop
      // #cards-area scrolls internally, but on mobile (esp. Chrome-on-Samsung)
      // the whole PAGE scrolls (the header scrolls away). Pinning the observer
      // to #cards-area meant that on Samsung the sections barely moved relative
      // to the observed root, so the green stuck during a fast fling. Viewport
      // intersection always reflects what's actually on screen, whatever scrolls.
      // rootMargin bottom -60% → the "active band" is the top 40% of the screen.
      const io = new IntersectionObserver((entries) => {{
        entries.forEach(e => {{ jumpVisible[e.target.id] = e.isIntersecting; }});
        recomputeActive();
        jumpDebug();
      }}, {{ root: null, rootMargin: '0px 0px -60% 0px', threshold: 0 }});
      secs.forEach(sec => io.observe(sec));
    }}

    // Fallback / initial paint only (used if IntersectionObserver is missing).
    function updateJumpSpy() {{
      const secs = jumpSections();
      if (!secs.length) return;
      let current = secs[0].id;
      const line = Math.max(120, (window.innerHeight || 600) * 0.4);
      secs.forEach(sec => {{
        if (sec.getBoundingClientRect().top <= line) current = sec.id;
      }});
      setActiveJump(current);
    }}
    document.addEventListener('DOMContentLoaded', () => {{
      jumpLinks().forEach(a => a.addEventListener('click', e => {{
        e.preventDefault();
        a.blur();                          // drop focus so no sticky :focus/:hover on touch
        setActiveJump(a.dataset.target);   // instant single-green, no stale state
        scrollToSection(a.dataset.target);
      }}));
      initJumpObserver();
      updateJumpSpy();                     // correct green on first paint
      // Debug overlay refresh (only when ?debug=1) — IO callbacks also refresh
      // it; this keeps the numbers live between callbacks.
      if (JUMP_DEBUG) (function dbg(){{ jumpDebug(); requestAnimationFrame(dbg); }})();
    }});

    function normalizeSearch(text) {{
      return text
        .replace(/cupboards?/gi, 'cupboard')
        .replace(/chests?/gi, 'chest')
        .replace(/drawers?/gi, 'drawer')
        .replace(/tables?/gi, 'table')
        .replace(/chairs?/gi, 'chair')
        .replace(/cabinets?/gi, 'cabinet')
        .replace(/bedsides?/gi, 'bedside')
        .replace(/wardrobes?/gi, 'wardrobe')
        .replace(/dressers?/gi, 'dresser')
        .replace(/shelves?/gi, 'shelf')
        .replace(/bookcase(s)?/gi, 'bookcase');
    }}

    function searchItems() {{
      const input = document.getElementById('searchInput');
      const query = input.value.toLowerCase().trim();
      const searchBox = document.getElementById('searchBox');
      const resultsEl = document.getElementById('searchResults');
      if (query) {{ searchBox.classList.add('has-text'); }}
      else {{ searchBox.classList.remove('has-text'); }}
      if (!query) {{
        document.querySelectorAll('.card').forEach(c => {{
          c.style.display = '';
        }});
        resultsEl.textContent = '';
        return;
      }}
      const normalizedQuery = normalizeSearch(query);
      let visibleCount = 0, totalCount = 0;
      document.querySelectorAll('.card').forEach(card => {{
        totalCount++;
        const titleEl = card.querySelector('.title');
        if (!titleEl) return;
        const title = titleEl.textContent.toLowerCase();
        const normalizedTitle = normalizeSearch(title);
        const queryWords = normalizedQuery.split(/\s+/);
        const matches = queryWords.every(word => normalizedTitle.includes(word));
        if (matches) {{
          card.style.display = ''; visibleCount++;
        }} else {{ card.style.display = 'none'; }}
      }});
      resultsEl.innerHTML = '<strong>' + visibleCount + '</strong> of ' + totalCount + ' lots';
    }}
    function clearSearch() {{
      document.getElementById('searchInput').value = '';
      searchItems();
      document.getElementById('searchInput').focus();
    }}

    // ── MAP ──
    const map = L.map('map', {{ center: [54.2, -2.5], zoom: 6, zoomControl: true }});
    L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
      attribution: '&copy; OSM &copy; CARTO',
      subdomains: 'abcd',
      maxZoom: 19
    }}).addTo(map);

    let markers = {{}};
    let highlightedMarker = null;

    for (const pc in PC_MAP) {{
      const h = PC_MAP[pc];
      const m = L.marker([h.lat, h.lng], {{
        icon: L.divIcon({{
          className: '',
          html: '<div class="pin-default"></div>',
          iconSize: [8, 8],
          iconAnchor: [4, 4]
        }})
      }});
      m.bindTooltip(h.name, {{ direction: 'top', offset: [0, -8] }});
      m.addTo(map);
      markers[pc] = m;
    }}

    // Returns the timing band class for a sale-date string like "📅 Wed 1st Jul 2026 10:30am BST"
    function saleBand(dateText) {{
      if (!dateText) return 'pin-none';
      const m = dateText.match(/(\\d{{1,2}})(?:st|nd|rd|th)?\\s+([A-Za-z]{{3,}})\\s+(\\d{{4}})/);
      if (!m) return 'pin-none';
      const months = {{jan:0,feb:1,mar:2,apr:3,may:4,jun:5,jul:6,aug:7,sep:8,oct:9,nov:10,dec:11}};
      const mon = months[m[2].slice(0,3).toLowerCase()];
      if (mon === undefined) return 'pin-none';
      const sale = new Date(+m[3], mon, +m[1]);
      const today = new Date(); today.setHours(0,0,0,0);
      const days = Math.round((sale - today) / 86400000);
      if (days <= 3) return 'pin-now';
      if (days <= 14) return 'pin-week';
      return 'pin-later';
    }}

    function highlightMarker(pc, band) {{
      if (highlightedMarker) {{
        highlightedMarker.setIcon(L.divIcon({{
          className: '',
          html: '<div class="pin-default"></div>',
          iconSize: [8, 8],
          iconAnchor: [4, 4]
        }}));
        const prev = document.querySelector('.house.highlighted');
        if (prev) prev.classList.remove('highlighted');
      }}
      if (!pc || !markers[pc]) {{ highlightedMarker = null; return; }}
      const m = markers[pc];
      m.setIcon(L.divIcon({{
        className: '',
        html: '<div class="pin-highlighted ' + (band || 'pin-none') + '"></div>',
        iconSize: [16, 16],
        iconAnchor: [8, 8]
      }}));
      highlightedMarker = m;
    }}

    // Hover ANYWHERE on a lot card highlights that lot's auction house on the
    // map (not just hovering the house name) — makes the map earn its place
    // instead of sitting blank. Postcode is read from the .house .pc inside the card.
    document.querySelectorAll('.card').forEach(card => {{
      const houseEl = card.querySelector('.house');
      const pcRaw = card.querySelector('.pc');
      if (!pcRaw) return;
      const pc = pcRaw.textContent.trim().replace(/\\s+/g, '').toUpperCase();
      const dateEl = card.querySelector('.saledate');
      const band = saleBand(dateEl ? dateEl.textContent : '');
      card.addEventListener('mouseenter', () => {{
        if (houseEl) houseEl.classList.add('highlighted');
        highlightMarker(pc, band);
      }});
      card.addEventListener('mouseleave', () => {{
        if (houseEl) houseEl.classList.remove('highlighted');
        highlightMarker(null);
      }});
    }});

    const allLats = Object.values(PC_MAP).map(h => h.lat);
    const allLngs = Object.values(PC_MAP).map(h => h.lng);
    const bounds = [[Math.min(...allLats), Math.min(...allLngs)], [Math.max(...allLats), Math.max(...allLngs)]];
    map.fitBounds(bounds, {{ padding: [30, 30] }});
    if (map.getZoom() > 8) map.setZoom(8);

    // ── MOBILE MAP OVERLAY TOGGLE ──
    function openMobileMap() {{
      document.body.classList.add('map-open');
      setTimeout(() => {{
        map.invalidateSize();
        map.fitBounds(bounds, {{ padding: [30, 30] }});
        if (map.getZoom() > 8) map.setZoom(8);
      }}, 60);
    }}
    function closeMobileMap() {{
      document.body.classList.remove('map-open');
    }}

    // ── Scroll progress counter ──
    // Updates each section's "X of Y seen" label as the user scrolls past
    // cards. Counts only currently-visible cards (offsetParent check) so it
    // stays accurate when the search box has filtered some lots out.
    (function initScrollProgress() {{
      const cardsArea = document.getElementById('cards-area');
      if (!cardsArea) return;
      const sections = Array.from(cardsArea.querySelectorAll('section[id]'));
      let ticking = false;
      function updateProgress() {{
        const headerBottom = cardsArea.getBoundingClientRect().top;
        sections.forEach(section => {{
          const progressEl = section.querySelector('.progress');
          if (!progressEl) return;
          const cards = Array.from(section.querySelectorAll('.card')).filter(c => c.offsetParent !== null);
          const total = cards.length;
          if (!total) {{ progressEl.textContent = ''; return; }}
          const passed = cards.filter(c => c.getBoundingClientRect().top < headerBottom).length;
          progressEl.textContent = passed > 0 ? `${{passed}} of ${{total}} seen` : '';
        }});
        ticking = false;
      }}
      cardsArea.addEventListener('scroll', () => {{
        if (!ticking) {{ requestAnimationFrame(updateProgress); ticking = true; }}
      }}, {{ passive: true }});
      updateProgress();
    }})();

    // ── Back to top ──
    function scrollCardsToTop() {{
      const cardsArea = document.getElementById('cards-area');
      if (cardsArea) cardsArea.scrollTo({{ top: 0, behavior: 'smooth' }});
    }}
    (function initBackToTop() {{
      const cardsArea = document.getElementById('cards-area');
      const btn = document.getElementById('back-to-top');
      if (!cardsArea || !btn) return;
      cardsArea.addEventListener('scroll', () => {{
        btn.classList.toggle('visible', cardsArea.scrollTop > 500);
      }}, {{ passive: true }});
    }})();
  </script>
</body>
</html>"""


def sweep_orphan_images(all_lots):
    """Delete image files in IMAGES_DIR not referenced by any current lot.
    A file only becomes orphaned AFTER its lot has left the data (i.e. the
    auction ended and the scrape no longer returns it), so this keeps
    images/ aligned with live lots. seen_lots.json is never touched.
    """
    referenced = {lot["img_file"] for lot in all_lots.values() if lot.get("img_file")}
    removed = 0
    freed = 0
    for p in IMAGES_DIR.iterdir():
        if p.is_file() and p.name not in referenced:
            try:
                freed += p.stat().st_size
                p.unlink()
                removed += 1
            except OSError as e:
                log.warning(f"Could not remove orphan {p.name}: {e}")
    log.info(f"Orphan sweep: removed {removed} images ({freed/1e6:.1f} MB freed)")


def git_push(repo_dir):
    # Under GitHub Actions the workflow handles commit/push; skip here.
    if os.environ.get("GITHUB_ACTIONS"):
        log.info("Git: running under GitHub Actions — workflow handles commit/push, skipping.")
        return
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    for cmd in [
        ["git", "-C", str(repo_dir), "add", "-A"],
        ["git", "-C", str(repo_dir), "commit", "-m", f"Auto update: {now_str}"],
        ["git", "-C", str(repo_dir), "push"],
    ]:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            if "nothing to commit" in result.stdout + result.stderr:
                log.info("Git: nothing to commit")
                return
            log.warning(f"Git failed: {' '.join(cmd)}\n{result.stderr}")
            return
    log.info("Git: pushed successfully")


# --- Sale-date enrichment -------------------------------------------------
# Sale-date strings come in several flavours:
#   Timed:  "Ends Sun 24th May 2026 from 2pm BST"
#   Live:   "Mon 25th May 2026 10am BST (Lots 1001 to 1502) Tue 26th May 2026 10am BST ..."
# We capture the full block for the future, and a short summary for display.
_SALE_DATE_RE = re.compile(
    r'((?:Ends\s+)?(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}\w{0,2}\s+'
    r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+20\d{2}'
    r'(?:\s+(?:from\s+)?\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*(?:GMT|BST)?)?)',
    re.IGNORECASE,
)


def fetch_sale_dates(session, sample_lot_url):
    """Fetch one lot page from an auction, return (summary, raw_block).
    summary = first date string, e.g. 'Sun 24th May 2026 from 2pm BST'
    raw_block = the entire 'Sale Dates: ...' text, for the tooltip.
    """
    try:
        r = session.get(sample_lot_url, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except Exception as e:
        log.debug(f"sale_dates fetch failed: {e}")
        return ("", "")

    soup = BeautifulSoup(r.text, "html.parser")
    label = soup.find(string=re.compile(r'Sale Dates?:', re.IGNORECASE))
    if not label:
        return ("", "")
    block = label.parent.parent if label.parent else None
    if not block:
        return ("", "")
    raw = re.sub(r'\s+', ' ', block.get_text(' ', strip=True))
    raw = re.sub(r'^Sale Dates?:\s*', '', raw, flags=re.IGNORECASE).strip()

    # First date string from the block
    m = _SALE_DATE_RE.search(raw)
    summary = m.group(1).strip() if m else raw[:80]
    return (summary, raw)


def enrich_with_sale_dates(session, all_lots):
    """For each unique auction_id, fetch one lot's page and apply the sale-date
    info to every lot in that auction."""
    # Group lots by auction_id
    by_auction = {}
    for lot in all_lots.values():
        aid = lot.get("auction_id") or ""
        if not aid:
            continue
        by_auction.setdefault(aid, []).append(lot)

    log.info(f"Fetching sale dates for {len(by_auction)} auctions…")
    for i, (aid, lots) in enumerate(by_auction.items(), 1):
        sample = lots[0]
        summary, raw = fetch_sale_dates(session, sample["url"])
        for lot in lots:
            lot["sale_date"] = summary
            lot["sale_dates_raw"] = raw
        if i % 25 == 0:
            log.info(f"  sale-dates progress: {i}/{len(by_auction)}")
        time.sleep(REQUEST_DELAY)


def main():
    log.info("=== Pinefinders Auction Finds — starting ===")
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    session  = requests.Session()
    all_lots = {}

    for term in SEARCH_TERMS:
        log.info(f"Searching: '{term}'")
        for lot in scrape_term(session, term):
            if lot["id"] not in all_lots:
                all_lots[lot["id"]] = lot
        if len(all_lots) >= MAX_LOTS:
            log.info(f"Cap reached ({MAX_LOTS}) — stopping")
            break

    log.info(f"Total unique lots: {len(all_lots)}")

    enrich_with_sale_dates(session, all_lots)

    log.info("Downloading images…")
    for lot in all_lots.values():
        if lot["img_url"] and lot["img_file"]:
            download_image(lot["img_url"], IMAGES_DIR / lot["img_file"])
            time.sleep(0.3)

    local_lots = [l for l in all_lots.values() if l["local"]]
    wide_lots  = [l for l in all_lots.values() if not l["local"]]
    log.info(f"Local: {len(local_lots)}  UK-wide: {len(wide_lots)}")

    # Load previously-seen lot IDs and postcode lookup
    seen = load_seen()
    postcodes = load_postcodes()
    new_count = sum(1 for lot_id in all_lots if lot_id not in seen)
    overlap   = len(seen.intersection(all_lots))
    log.info(f"Seen-before: {overlap}  New since last run: {new_count}")
    log.info(f"Postcode lookup: {len(postcodes[0])} houses")

    (REPO_DIR / "index.html").write_text(
        build_html(local_lots, wide_lots, seen=seen, postcodes=postcodes),
        encoding="utf-8",
    )
    (REPO_DIR / "data.json").write_text(
        json.dumps(list(all_lots.values()), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("HTML written")

    # Update seen_lots.json with this run's lot IDs (union, capped at 5000)
    updated_seen = (seen | set(all_lots.keys()))
    # Keep the file from growing unboundedly: prefer recent IDs
    if len(updated_seen) > 5000:
        updated_seen = set(list(all_lots.keys())) | set(list(seen))[: 5000 - len(all_lots)]
    save_seen(updated_seen)
    log.info(f"Updated seen_lots.json ({len(updated_seen)} ids)")

    # Keep images/ aligned with live lots (delete ended-auction leftovers)
    sweep_orphan_images(all_lots)

    log.info("Pushing to GitHub…")
    git_push(REPO_DIR)
    log.info("=== Done ===")


if __name__ == "__main__":
    main()
