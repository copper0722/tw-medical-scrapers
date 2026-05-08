#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# /// script
# requires-python = ">=3.10"
# dependencies = ["cloudscraper", "beautifulsoup4"]
# ///
"""
nhi_page_monitor.py — Watch NHI 健保署 static pages for PDF/doc/spreadsheet attachments.

Pages monitored (curated 2026-04 by clinic relevance; lp-6109 is the canonical
透析會議紀錄 page that surfaces NHI dialysis budget meeting minutes):

  lp-3719 新增/修訂支付標準診療項目
  lp-3778 支付標準
  lp-3721 支付標準未列項目
  lp-3725 支付標準其他
  lp-6109 透析會議紀錄          ← critical for clinic-policy tracking

For each page, find every <a href> ending in .pdf/.odt/.ods/.doc/.docx/.xls/.xlsx
inside <main>, emit one JSONL row per file (gov-docs ingest contract).
Downstream: import_gov_docs_to_pg.py UPSERTs into tw_gov_docs.

Each emitted row has source='page_monitor', doc_type='announcement', publisher='NHI'.
The actual PDF binary is NOT downloaded here — only the URL + title catalogued.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    import cloudscraper
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: pip3 install cloudscraper beautifulsoup4", file=sys.stderr)
    sys.exit(1)

BASE = "https://www.nhi.gov.tw"

# (listing_id, name, page_url)
PAGES = [
    ("lp-3719", "新增/修訂支付標準診療項目", f"{BASE}/ch/lp-3719-1.html"),
    ("lp-3778", "支付標準",                f"{BASE}/ch/lp-3778-1.html"),
    ("lp-3721", "支付標準未列項目",         f"{BASE}/ch/lp-3721-1.html"),
    ("lp-3725", "支付標準其他",            f"{BASE}/ch/lp-3725-1.html"),
    ("lp-6109", "透析會議紀錄",            f"{BASE}/ch/lp-6109-1.html"),
]

DOC_EXTS = (".pdf", ".odt", ".odp", ".ods", ".doc", ".docx", ".xls", ".xlsx")


def fetch(scraper, url: str) -> str:
    r = scraper.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def extract_doc_links(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("main") or soup
    out = []
    seen: set[str] = set()
    for a in main.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href or not href.lower().endswith(DOC_EXTS):
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        title = (a.get_text(strip=True) or "").strip()
        if not title or title.lower() in ("pdf", "odt", "ods", "doc", "docx", "xls", "xlsx"):
            # use filename as fallback
            title = Path(urlparse(url).path).stem or url
        out.append({"url": url, "title": title})
    return out


def make_uid(url: str) -> str:
    """Use NHI dl-XXXXX pattern when present, else sha1 of full URL."""
    parsed = urlparse(url)
    parts = parsed.path.rsplit("/", 2)
    for part in parts[-2:]:
        if part.startswith("dl-"):
            return f"nhi:{part.split('-')[0]}-{part.split('-')[1]}"
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    return f"nhi:page-monitor-{h}"


def build_row(file_info: dict, listing_id: str, page_url: str) -> dict:
    return {
        "uid": make_uid(file_info["url"]),
        "uid_source": "url_id",
        "ref_number": None,
        "title": file_info["title"],
        "publisher": "NHI",
        "doc_type": "announcement",
        "publish_date": None,
        "effective_date": None,
        "source": "page_monitor",
        "urls": [
            {"url": file_info["url"], "url_source": "page_attachment",
             "url_id": None, "source": "page_monitor"},
            {"url": page_url, "url_source": "page_listing",
             "url_id": listing_id, "source": "page_monitor"},
        ],
        "files": [{
            "path": None,
            "filename": Path(urlparse(file_info["url"]).path).name,
            "size_bytes": None,
            "sha256": None,
            "extracted_md": None,
        }],
        "content": None,
        "tags": [listing_id],
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--page", default=None,
                   help="Subset filter: lp-id substring")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    scraper = cloudscraper.create_scraper()
    pages = PAGES if not args.page else [p for p in PAGES if args.page in p[0]]
    if not pages:
        print(f"no pages matched {args.page!r}", file=sys.stderr)
        return 1

    rows: list[dict] = []
    for listing_id, name, page_url in pages:
        try:
            html = fetch(scraper, page_url)
        except Exception as e:
            print(f"FAIL {listing_id}: {e}", file=sys.stderr)
            continue
        files = extract_doc_links(html, page_url)
        print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] "
              f"{listing_id} ({name}): {len(files)} attachments", file=sys.stderr)
        for f in files:
            rows.append(build_row(f, listing_id, page_url))

    print(f"total: {len(rows)} attachment rows across {len(pages)} page(s)", file=sys.stderr)

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
