"""
QNTM — Rebuild the scan universe from the Russell 1000 (iShares IWB holdings)
=============================================================================
The scanned universe is `universe_data.SECTORS` (data_refresh does
`tickers = list(SECTORS.keys())`). This script regenerates that dict from the
canonical Russell 1000 proxy — the iShares IWB ETF holdings file — so the scan
covers the actual index (~1,000 names) instead of a hand-seeded subset.

It does NOT touch the FUNDAMENTALS block (those are static fallbacks; live
fundamentals + mktcap are fetched per-ticker at refresh time, so new names work
without a static entry). It writes a NEW file you review and then swap in.

Run it again after each June reconstitution to stay in sync.

USAGE (from the repo root, where universe_data.py lives):
    python build_universe.py                    # download IWB, write universe_data.generated.py
    python build_universe.py --dry-run          # just show the add/drop diff
    python build_universe.py --from-file IWB_holdings.csv   # parse a CSV you downloaded by hand
    python build_universe.py --out universe_data.py         # overwrite in place (after you trust it)

If the direct download 403s (iShares sometimes blocks non-browser requests),
open the IWB product page, click "Data Download", save the CSV, and use
--from-file. The parser handles the iShares preamble/footer either way.
"""

import os, sys, csv, io, argparse, logging
from datetime import date

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("qntm.universe")

# iShares IWB (Russell 1000) holdings CSV endpoint.
IWB_URL = ("https://www.ishares.com/us/products/239707/ishares-russell-1000-etf/"
           "1467271812596.ajax?fileType=csv&fileName=IWB_holdings&dataType=fund")

# iShares uses GICS sector names; map them to QNTM's 11 labels (these MUST match
# the keys in model_engine.SECTOR_EVENT_MAP or the macro overlay can't tilt them).
SECTOR_MAP = {
    "Information Technology":  "Technology",
    "Financials":             "Financials",
    "Health Care":            "Healthcare",
    "Consumer Discretionary": "Consumer Discretionary",
    "Communication":          "Comm Services",
    "Communication Services": "Comm Services",
    "Industrials":            "Industrials",
    "Consumer Staples":       "Consumer Staples",
    "Energy":                 "Energy",
    "Utilities":              "Utilities",
    "Real Estate":            "Real Estate",
    "Materials":              "Materials",
}

# Asset-class rows that are not common equity — skipped (cash, futures, etc.).
EQUITY_CLASSES = {"Equity"}

# iShares concatenates share-class letters (e.g. "BRKB"); Yahoo/yfinance wants a
# hyphen for THESE specific multi-class names. This is a curated allow-list on
# purpose: genuinely single-class tickers that merely end in A/B/C (FOXA, NWSA,
# RUSHA, GOOGL, NVDA…) are the real exchange symbols yfinance accepts as-is and
# must NOT be touched. Extend this if a future reconstitution adds a class share
# that yfinance hyphenates. (A wrong symbol just means that one name gets no live
# data and falls back to static — visible in the nightly --force logs.)
TICKER_FIXUPS = {
    "BRKA": "BRK-A", "BRKB": "BRK-B",
    "BFA":  "BF-A",  "BFB":  "BF-B",
    "LENB": "LEN-B",
    "HEIA": "HEI-A",
    "MOGA": "MOG-A", "MOGB": "MOG-B",
    "CWENA": "CWEN-A",
    "LGFA": "LGF-A", "LGFB": "LGF-B",
    "GEFB": "GEF-B",
    "UHALB": "UHAL-B",
}


# ── download ──────────────────────────────────────────────────────────────────
def download_holdings(url: str) -> str:
    import requests
    headers = {
        # iShares 403s default agents — present as a browser.
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36"),
        "Accept": "text/csv,application/csv,*/*",
    }
    log.info("Downloading IWB holdings from iShares…")
    r = requests.get(url, headers=headers, timeout=60)
    r.raise_for_status()
    if "Ticker" not in r.text[:5000] and "ticker" not in r.text[:5000]:
        raise RuntimeError("Downloaded file doesn't look like an iShares holdings CSV. "
                           "Use --from-file with a manually downloaded CSV.")
    return r.text


# ── parse ─────────────────────────────────────────────────────────────────────
# iShares serves holdings in two shapes depending on the route:
#   • the page "Download" → Microsoft SpreadsheetML 2003 XML (".xls" extension)
#   • the .ajax CSV endpoint → plain CSV (when not consent-gated)
# parse_holdings() auto-detects and normalises both to a list of rows, then a
# single extractor turns rows → {TICKER: app_sector}.

def _csv_rows(text: str) -> list:
    return list(csv.reader(io.StringIO(text)))


def _xml_rows(text: str) -> list:
    """Rows from the iShares SpreadsheetML 'Holdings' worksheet, honouring
    ss:Index so sparse/blank cells don't shift columns."""
    import xml.etree.ElementTree as ET
    NS = "urn:schemas-microsoft-com:office:spreadsheet"
    q = lambda tag: f"{{{NS}}}{tag}"
    import re
    # iShares SpreadsheetML ships bare '&' (in URLs and names like "Cohen & Steers")
    # which strict XML parsers reject — escape any '&' that isn't already an entity.
    text = re.sub(r'&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)', '&amp;', text)
    try:
        root = ET.fromstring(text)
    except ValueError:
        # XML declaration carried an encoding attr — ET rejects str then; use bytes.
        root = ET.fromstring(text.encode("utf-8"))
    ws = next((w for w in root.iter(q("Worksheet")) if w.get(q("Name")) == "Holdings"), None)
    if ws is None:
        raise RuntimeError("No 'Holdings' worksheet found in the iShares XML file.")
    table = ws.find(q("Table"))
    out = []
    for row in table.findall(q("Row")):
        cells, col = [], 0
        for cell in row.findall(q("Cell")):
            idx = cell.get(q("Index"))
            if idx:
                col = int(idx) - 1          # ss:Index is 1-based; jump to it
            data = cell.find(q("Data"))
            val = data.text if (data is not None and data.text is not None) else ""
            while len(cells) < col:
                cells.append("")            # pad skipped (blank) columns
            cells.append(val)
            col += 1
        out.append(cells)
    return out


def _rows_to_records(rows: list):
    """rows (incl. preamble + header) → (records, {unmapped_gics: n}) where each
    record is {ticker, sector, weight}. weight = fund weight (%), used to rank a
    gem layer; 0.0 when the column is absent."""
    hdr_idx = None
    for i, row in enumerate(rows):
        cells = [str(c).strip().strip('"') for c in row]
        if "Ticker" in cells and "Sector" in cells:
            hdr_idx = i
            break
    if hdr_idx is None:
        raise RuntimeError("Could not find the 'Ticker','Sector' header row.")

    header = [str(c).strip().strip('"') for c in rows[hdr_idx]]
    idx = {name: header.index(name) for name in header}
    ti = idx["Ticker"]
    si = idx.get("Sector")
    ai = idx.get("Asset Class")
    wi = idx.get("Weight (%)")

    records, unmapped, seen = [], {}, set()
    need = max(ti, si or 0, ai or 0, wi or 0)
    for row in rows[hdr_idx + 1:]:
        if not row or len(row) <= need:
            continue  # blank lines, footer disclaimer, short rows
        tk = str(row[ti]).strip().strip('"')
        if not tk or tk in ("-", "--"):
            continue  # cash/blank rows
        aclass = (str(row[ai]).strip().strip('"') if (ai is not None and ai < len(row)) else "Equity")
        if aclass and aclass not in EQUITY_CLASSES:
            continue  # skip futures/cash/money-market lines
        gics = (str(row[si]).strip().strip('"') if (si is not None and si < len(row)) else "")
        app_sector = SECTOR_MAP.get(gics)
        if app_sector is None:
            unmapped[gics] = unmapped.get(gics, 0) + 1
            continue  # don't pollute the universe with an Unknown sector
        norm = tk.upper().replace(".", "-").strip()
        norm = TICKER_FIXUPS.get(norm, norm)   # iShares concat → yfinance hyphen
        if norm in seen:
            continue
        seen.add(norm)
        weight = 0.0
        if wi is not None and wi < len(row):
            try:
                weight = float(str(row[wi]).replace(",", "").strip().strip('"') or 0)
            except ValueError:
                weight = 0.0
        records.append({"ticker": norm, "sector": app_sector, "weight": weight})
    return records, unmapped


def _detect_and_rows(text: str) -> list:
    head = text[:2000].lstrip().lower()
    if head.startswith("<!doctype html") or head.startswith("<html") or "<head>" in head[:300]:
        raise RuntimeError(
            "Got an HTML page, not holdings data — this is iShares' investor-consent "
            "splash. Accept the investor-type prompt on ishares.com, then download via "
            "the Holdings table (gives a SpreadsheetML .xls) and re-run with --from-file."
        )
    if text.lstrip().startswith("<?xml") or "urn:schemas-microsoft-com:office:spreadsheet" in text[:1000]:
        return _xml_rows(text)
    return _csv_rows(text)


def parse_records(text: str):
    """(records, unmapped) from an iShares holdings file (SpreadsheetML or CSV)."""
    return _rows_to_records(_detect_and_rows(text))


def parse_holdings(text: str):
    """Back-compat: {TICKER: app_sector}, plus a dict of unmapped GICS sectors."""
    records, unmapped = parse_records(text)
    return {r["ticker"]: r["sector"] for r in records}, unmapped


# ── emit ──────────────────────────────────────────────────────────────────────
def render_sectors_block(sectors: dict) -> str:
    lines = ["SECTORS = {"]
    for tk in sorted(sectors):
        lines.append(f'    "{tk}": "{sectors[tk]}",')
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_pool_block(pool: set) -> str:
    if not pool:
        return ""
    lines = [
        "",
        "# SMALL_MID_POOL — small-cap names (top of the Russell 2000 via iShares IWM)",
        "# added as hidden-gem material. detect_hidden_gems() treats these as gem-",
        "# eligible even when a live market cap is missing, so a genuine small-cap is",
        "# not excluded by a yfinance data gap. The screener and model portfolio use",
        "# the full SECTORS universe; only the gem screen leans on this set.",
        "SMALL_MID_POOL = {",
    ]
    for tk in sorted(pool):
        lines.append(f'    "{tk}",')
    lines.append("}")
    return "\n".join(lines) + "\n"


def splice_into_universe(in_path: str, sectors: dict, pool: set = None) -> str:
    """Return new universe_data.py text: replace the SECTORS dict literal (and an
    existing SMALL_MID_POOL block if present), preserving the docstring/imports
    above and the `_f` helper + FUNDAMENTALS below, verbatim."""
    with open(in_path, "r") as f:
        lines = f.read().splitlines(keepends=True)
    s_start = next((i for i, l in enumerate(lines) if l.lstrip().startswith("SECTORS")), None)
    if s_start is None:
        raise RuntimeError("Couldn't locate the SECTORS assignment in universe_data.py.")
    s_close = next((j for j in range(s_start + 1, len(lines)) if lines[j].startswith("}")), None)
    if s_close is None:
        raise RuntimeError("Couldn't find the closing brace of the SECTORS dict.")
    # Absorb an existing SMALL_MID_POOL block (re-runs) so we don't duplicate it.
    cut = s_close
    f_start = next((j for j in range(s_close + 1, len(lines))
                    if lines[j].lstrip().startswith(("FUNDAMENTALS", "def _f"))), len(lines))
    p_start = next((j for j in range(s_close + 1, f_start)
                    if lines[j].lstrip().startswith("SMALL_MID_POOL")), None)
    if p_start is not None:
        p_close = next((j for j in range(p_start + 1, len(lines)) if lines[j].startswith("}")), p_start)
        cut = p_close
    pre  = "".join(lines[:s_start])
    post = "".join(lines[cut + 1:])
    banner = (f"# SECTORS — Russell 1000 core (iShares IWB) + small-cap gem layer (top of\n"
              f"# iShares IWM), regenerated by build_universe.py on {date.today().isoformat()}.\n"
              f"# {len(sectors)} names. Re-run after each June reconstitution; edit the source,\n"
              f"# not this file.\n")
    return pre + banner + render_sectors_block(sectors) + render_pool_block(pool or set()) + post


# ── diff ──────────────────────────────────────────────────────────────────────
def current_sectors(in_path: str) -> dict:
    d = os.path.dirname(os.path.abspath(in_path))
    sys.path.insert(0, d)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_cur_universe", in_path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return dict(getattr(m, "SECTORS", {}))
    except Exception as e:
        log.warning(f"Could not import current SECTORS for diff: {e}")
        return {}


def print_diff(old: dict, new: dict):
    from collections import Counter
    o, n = set(old), set(new)
    adds, drops = sorted(n - o), sorted(o - n)
    log.info(f"\n── DIFF ──  current {len(o)} → new {len(n)}  ({len(n)-len(o):+d})")
    log.info(f"  + {len(adds)} added, - {len(drops)} dropped")
    if adds:
        log.info(f"  added (first 40): {adds[:40]}")
    if drops:
        log.info(f"  dropped (first 40): {drops[:40]}")
    log.info("  new sector distribution:")
    for sec, cnt in sorted(Counter(new.values()).items(), key=lambda x: -x[1]):
        log.info(f"    {sec}: {cnt}")


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in",  dest="in_path",  default="universe_data.py",
                    help="existing universe_data.py to read FUNDAMENTALS from")
    ap.add_argument("--out", dest="out_path", default="universe_data.generated.py",
                    help="where to write the regenerated file")
    ap.add_argument("--from-file", dest="csv_file", default=None,
                    help="locally-saved IWB (Russell 1000) holdings file; else download")
    ap.add_argument("--gem-file", dest="gem_file", default=None,
                    help="iShares IWM (Russell 2000) holdings file — its top slice becomes "
                         "the small-cap hidden-gem layer (SMALL_MID_POOL)")
    ap.add_argument("--gem-top", type=int, default=400,
                    help="how many of the largest IWM names (by fund weight) to add as the "
                         "gem layer, skipping any already in the R1000 core (default 400)")
    ap.add_argument("--url", default=IWB_URL, help="override the iShares IWB holdings URL")
    ap.add_argument("--dry-run", action="store_true", help="show the diff, write nothing")
    args = ap.parse_args()

    # ── core: Russell 1000 (IWB) ──────────────────────────────────────────────
    if args.csv_file:
        log.info(f"Reading IWB (core) holdings from {args.csv_file}")
        with open(args.csv_file, "r", encoding="utf-8-sig") as f:
            core_text = f.read()
    else:
        core_text = download_holdings(args.url)

    core_records, unmapped = parse_records(core_text)
    core_sectors = {r["ticker"]: r["sector"] for r in core_records}
    log.info(f"Core (Russell 1000): {len(core_sectors)} tickers.")
    if unmapped:
        log.warning(f"Core skipped {sum(unmapped.values())} rows with unmapped sectors: {unmapped}.")
    if len(core_sectors) < 800:
        log.error(f"Only {len(core_sectors)} core tickers parsed — suspiciously low; not writing.")
        sys.exit(1)

    sectors = dict(core_sectors)
    pool = set()

    # ── gem layer: top slice of Russell 2000 (IWM) ────────────────────────────
    if args.gem_file:
        log.info(f"Reading IWM (gem layer) holdings from {args.gem_file}")
        with open(args.gem_file, "r", encoding="utf-8-sig") as f:
            gem_text = f.read()
        gem_records, gem_unmapped = parse_records(gem_text)
        gem_records.sort(key=lambda r: r["weight"], reverse=True)
        for r in gem_records:
            if len(pool) >= args.gem_top:
                break
            tk = r["ticker"]
            if tk in core_sectors:
                continue   # already in the R1000 core; not a net-new small-cap
            sectors[tk] = r["sector"]
            pool.add(tk)
        log.info(f"Gem layer: added {len(pool)} small-caps from the top {args.gem_top} IWM names "
                 f"(by weight), excluding any already in the core.")
        if gem_unmapped:
            log.warning(f"Gem layer skipped unmapped sectors: {gem_unmapped}.")
    else:
        log.warning("No --gem-file given: building R1000 core only (no small-cap gem layer). "
                    "Pass --gem-file <IWM holdings> to add hidden-gem material.")

    print_diff(current_sectors(args.in_path), sectors)
    log.info(f"Total universe: {len(sectors)}  (core {len(core_sectors)} + gem pool {len(pool)})")

    if args.dry_run:
        log.info("[DRY RUN] No file written.")
        return

    new_text = splice_into_universe(args.in_path, sectors, pool)
    with open(args.out_path, "w") as f:
        f.write(new_text)
    log.info(f"\nWrote {args.out_path}. Review the diff vs {args.in_path}, then swap it in:")
    log.info(f"    diff {args.in_path} {args.out_path}")
    log.info(f"    mv {args.out_path} {args.in_path}")


if __name__ == "__main__":
    main()
