#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# /// script
# requires-python = ">=3.10"
# dependencies = ["cloudscraper", "beautifulsoup4"]
# ///
"""
nhi_listing_scrape.py — Standalone HTML scrape for NHI 健保署 announcement listings.

Listings (paginated HTML, each item has cp-XXXXX URL pattern):
  3257  健保公告      (lp-3257-1.html)  doc_type=announcement
  3258  法規公告      (lp-3258-1.html)  doc_type=regulation
  3708  支付標準異動   (np-3708-1.html)  doc_type=announcement (sometimes np-* path)

Use this for HISTORICAL DEPTH that the RSS feed (nhi_regulation_rss.py) can't
reach — RSS only exposes ~20 most-recent items, listings paginate back years.

Pages are sometimes JavaScript-rendered; cloudscraper handles Cloudflare but if
the listing returns no items, fall back to the RSS-only flow for that listing.

Emits JSONL on stdout or --out matching the gov-docs ingest contract.
Downstream: import_gov_docs_to_pg.py.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

try:
    import cloudscraper
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: pip3 install cloudscraper beautifulsoup4", file=sys.stderr)
    sys.exit(1)

BASE = "https://www.nhi.gov.tw/ch/"

LISTINGS = [
    ("3257", "健保公告",       "lp-3257-1.html", "announcement"),
    ("3258", "法規公告",       "lp-3258-1.html", "regulation"),
    ("3708", "支付標準異動",   "np-3708-1.html", "announcement"),
]

REF_RE = re.compile(r"((?:健保|衛部|衛署|衛福部|部授)[一-龥]{0,4}字第\d+[A-Z]?號)")
ROC_DATE_RE = re.compile(r"(\d{2,3})[年./-](\d{1,2})[月./-](\d{1,2})日?")


def extract_ref(text: str) -> str | None:
    m = REF_RE.search(text or "")
    return m.group(1) if m else None


def roc_to_iso(text: str) -> str | None:
    """Try ROC date (民國 YYY-MM-DD or YYY/MM/DD or YYY 年 MM 月 DD 日) → ISO YYYY-MM-DD."""
    if not text:
        return None
    m = ROC_DATE_RE.search(text)
    if not m:
        return None
    y, mo, d = m.groups()
    try:
        return f"{int(y) + 1911:04d}-{int(mo):02d}-{int(d):02d}"
    except Exception:
        return None


def extract_items(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Parse either the table layout or ul-list layout."""
    items: list[dict] = []
    seen: set[str] = set()
    # try table first
    for tr in soup.select("table tbody tr"):
        a = tr.select_one("a[href*=cp-]")
        if not a:
            continue
        href = a.get("href", "").strip()
        if not href or "cp-" not in href:
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        title = a.get_text(strip=True)
        # date column (tries time tag first, then any td that looks like ROC date)
        date_text = ""
        time_el = tr.select_one("time")
        if time_el:
            date_text = time_el.get("datetime") or time_el.get_text(strip=True)
        if not date_text:
            for td in tr.select("td"):
                if ROC_DATE_RE.search(td.get_text()):
                    date_text = td.get_text(strip=True)
                    break
        items.append({"url": url, "title": title, "date_text": date_text})
    if items:
        return items
    # fallback: ul/li layout
    for li in soup.select(".rwd-list li, .list li, ul li"):
        a = li.select_one("a[href*=cp-]")
        if not a:
            continue
        href = a.get("href", "").strip()
        if not href or "cp-" not in href:
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        title = a.get_text(strip=True)
        date_text = ""
        for tag in li.find_all(["time", "span", "small"]):
            if ROC_DATE_RE.search(tag.get_text()):
                date_text = tag.get_text(strip=True)
                break
        items.append({"url": url, "title": title, "date_text": date_text})
    return items


def derive_uid(url: str, ref: str | None) -> tuple[str, str]:
    if ref:
        return (f"gov:{ref}", "ref_number")
    m = re.search(r"(cp|sp|np)-(\d+)", url)
    if m:
        return (f"nhi:{m.group(0)}", "url_id")
    return (f"nhi:listing-{abs(hash(url)) & 0xffffffff:x}", "url_hash")


def scrape_listing(scraper, listing_id: str, listing_name: str,
                   url_path: str, doc_type: str, max_pages: int = 5,
                   page_size: int = 60) -> list[dict]:
    rows: list[dict] = []
    for pi in range(1, max_pages + 1):
        url = f"{BASE}{url_path}?pi={pi}&ps={page_size}"
        try:
            r = scraper.get(url, timeout=30)
            r.raise_for_status()
        except Exception as e:
            print(f"  page {pi}: {e}", file=sys.stderr)
            break
        soup = BeautifulSoup(r.text, "html.parser")
        items = extract_items(soup, url)
        if not items:
            break
        for it in items:
            ref = extract_ref(it["title"])
            uid, uid_source = derive_uid(it["url"], ref)
            rows.append({
                "uid": uid,
                "uid_source": uid_source,
                "ref_number": ref,
                "title": it["title"],
                "publisher": "NHI",
                "doc_type": doc_type,
                "publish_date": roc_to_iso(it.get("date_text", "")),
                "effective_date": None,
                "source": f"scraper_{listing_id}",
                "urls": [{"url": it["url"], "url_source": "html_a",
                          "url_id": None, "source": f"scraper_{listing_id}"}],
                "files": [],
                "content": None,
                "tags": [f"lp-{listing_id}", listing_name],
            })
        print(f"  page {pi}: +{len(items)} (cumulative {len(rows)})", file=sys.stderr)
        if len(items) < page_size:
            break
    return rows


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--listing", default=None,
                   help="Subset filter: '3257'|'3258'|'3708' (default: all)")
    p.add_argument("--max-pages", type=int, default=5,
                   help="Pages per listing (default 5; ~300 items each)")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    scraper = cloudscraper.create_scraper()
    listings = [l for l in LISTINGS if not args.listing or args.listing in l[0]]
    if not listings:
        print(f"no listing matched {args.listing!r}", file=sys.stderr)
        return 1

    rows: list[dict] = []
    for lid, name, path, doc_type in listings:
        print(f"--- {name} ({lid}) ---", file=sys.stderr)
        items = scrape_listing(scraper, lid, name, path, doc_type, max_pages=args.max_pages)
        print(f"{lid} total: {len(items)}", file=sys.stderr)
        rows.extend(items)

    print(f"total: {len(rows)} rows across {len(listings)} listing(s)", file=sys.stderr)

    if args.dry_run:
        for r in rows[:3]:
            print(f"  sample: {r['uid']}  {r['title'][:60]}", file=sys.stderr)
        return 0

    if args.out:
        with args.out.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"wrote {len(rows)} rows → {args.out}", file=sys.stderr)
    else:
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
