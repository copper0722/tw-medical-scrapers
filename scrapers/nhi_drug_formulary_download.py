#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "cloudscraper>=1.2.71",
#   "beautifulsoup4>=4.12",
# ]
# ///
"""
nhi_drug_formulary_download.py — Standalone NHI 健保用藥品項月查詢檔 downloader.

Source: https://www.nhi.gov.tw/ch/lp-2466-1.html (Cloudflare-protected)
NHI publishes the drug formulary on the 25th-ish of each month.

Two equivalents are downloaded per period:
  - .B5  (Big5 fixed-width 1859 bytes/line — canonical source)
  - .TXT (UTF-8 derivative)

Run with `uv run`:
    uv run nhi_drug_formulary_download.py

Or with classic pip:
    pip install --user cloudscraper beautifulsoup4
    python3 nhi_drug_formulary_download.py

Usage:
  nhi_drug_formulary_download.py                       # auto-detect newest period
  nhi_drug_formulary_download.py --year 115 --month 5  # specific (ROC year, month)
  nhi_drug_formulary_download.py --dry-run             # show URLs only
  nhi_drug_formulary_download.py --out /path/to/dir    # custom output dir
                                                       # (default ./nhi-drug-formulary)
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

try:
    import cloudscraper
    from bs4 import BeautifulSoup
except ImportError as e:
    sys.exit(
        "Missing dependency: " + str(e)
        + "\nInstall:  pip install --user cloudscraper beautifulsoup4"
        + "\nOr run:   uv run nhi_drug_formulary_download.py  (auto-installs)"
    )

NHI_BASE = "https://www.nhi.gov.tw"
NHI_LISTING = NHI_BASE + "/ch/lp-2466-1.html"

DEFAULT_OUT = Path.cwd() / "nhi-drug-formulary"


def find_subpage(scraper, year_roc=None, month=None):
    """Return (label, sub_url, year_roc, month). Auto-detect newest if year/month omitted."""
    r = scraper.get(NHI_LISTING, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    candidates = []
    pat = re.compile(r"健保用藥品項(\d{2,3})年(\d{1,2})月查詢檔")
    for a in soup.find_all("a", href=True):
        text = (a.get_text() or "").strip()
        m = pat.search(text)
        if not m:
            continue
        y, mm = int(m.group(1)), int(m.group(2))
        href = a["href"]
        if href.startswith("/"):
            href = NHI_BASE + href
        candidates.append((y, mm, text, href))

    if not candidates:
        sys.exit("ERROR: no '健保用藥品項Y年M月查詢檔' link found on listing page")

    candidates.sort(reverse=True)
    if year_roc and month:
        for y, mm, t, h in candidates:
            if y == year_roc and mm == month:
                return t, h, y, mm
        sys.exit(f"ERROR: no match for {year_roc}年{month}月 on listing")
    y, mm, t, h = candidates[0]
    return t, h, y, mm


def find_zip_urls(scraper, sub_url):
    r = scraper.get(sub_url, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    urls = []
    for a in soup.find_all("a", href=True):
        h = a["href"]
        if ".zip" not in h.lower():
            continue
        if h.startswith("/"):
            h = NHI_BASE + h
        urls.append(h)
    if len(urls) < 2:
        sys.exit(f"ERROR: expected 2 ZIPs on sub-page, found {len(urls)}: {urls}")
    return urls


def classify_zip(scraper, url):
    """Probe Content-Disposition to label as 'b5' vs 'txt'."""
    r = scraper.head(url, timeout=20, allow_redirects=True)
    cd = r.headers.get("Content-Disposition", "")
    if "txt" in cd.lower():
        return "txt"
    if "b5" in cd.lower():
        return "b5"
    return "b5"


def download(scraper, url, out_path):
    r = scraper.get(url, timeout=120)
    r.raise_for_status()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(r.content)
    return len(r.content)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--year", type=int, help="ROC year (e.g. 115 = 2026)")
    ap.add_argument("--month", type=int, help="month 1-12")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help="output directory (default: ./nhi-drug-formulary)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-archive", action="store_true",
                    help="skip _archive copy (default: archive .b5 zip)")
    args = ap.parse_args()

    scraper = cloudscraper.create_scraper()
    label, sub_url, y, mm = find_subpage(scraper, args.year, args.month)
    iso_year = y + 1911
    period = f"{iso_year:04d}{mm:02d}"

    print(f"[+] Target: {label}")
    print(f"    Sub-page: {sub_url}")
    print(f"    Period:   {period}")

    zip_urls = find_zip_urls(scraper, sub_url)
    print(f"    ZIP URLs:")
    for u in zip_urls:
        print(f"      {u}")

    if args.dry_run:
        return

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    arch_dir = out_dir / "_archive"
    if not args.no_archive:
        arch_dir.mkdir(parents=True, exist_ok=True)

    for url in zip_urls:
        kind = classify_zip(scraper, url)
        out = out_dir / f"{period}_nhi_{kind}.zip"
        if out.exists():
            print(f"[-] Skipping {out.name} (exists, {out.stat().st_size:,} bytes)")
            continue
        size = download(scraper, url, out)
        print(f"[+] Downloaded {out.name} ({size:,} bytes)")
        if kind == "b5" and not args.no_archive:
            shutil.copy2(out, arch_dir / out.name)
            print(f"    Archived to {arch_dir / out.name}")


if __name__ == "__main__":
    main()
