#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
tfda_drug_download.py — Standalone TFDA 藥品許可證 + 處方成份 open-data ZIPs.

Source: https://data.fda.gov.tw/opendata/exportDataList.do
TFDA publishes weekly. ZIPs contain a single JSON file each:
  InfoId=36 → tfda_permits  (~66K records, 藥品許可證)
  InfoId=43 → tfda_ingredients (~125K records, 處方成份)

Public open data — no Cloudflare challenge, plain urllib works.

Usage:
  uv run tfda_drug_download.py
  python3 tfda_drug_download.py --out /path/to/dir
  python3 tfda_drug_download.py --dry-run
"""

import argparse
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

PERMITS_URL = "https://data.fda.gov.tw/opendata/exportDataList.do?method=ExportData&InfoId=36&logType=3"
INGREDIENTS_URL = "https://data.fda.gov.tw/opendata/exportDataList.do?method=ExportData&InfoId=43&logType=3"

DEFAULT_OUT = Path.cwd() / "tfda-drugs"


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def download(url, out_path):
    """Stream download with progress."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "tfda-drug-download/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(out_path, "wb") as f:
        chunk = r.read(64 * 1024)
        n = 0
        while chunk:
            f.write(chunk)
            n += len(chunk)
            chunk = r.read(64 * 1024)
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help="output directory (default: ./tfda-drugs)")
    ap.add_argument("--dry-run", action="store_true",
                    help="show URLs, do not download")
    ap.add_argument("--no-archive", action="store_true",
                    help="skip _archive/{YYYYMMDD}/ snapshot copy")
    args = ap.parse_args()

    today = datetime.now().strftime("%Y%m%d")

    log(f"=== TFDA drug open-data download ===")
    log(f"  URL permits:     {PERMITS_URL}")
    log(f"  URL ingredients: {INGREDIENTS_URL}")
    log(f"  Out:             {args.out}")

    if args.dry_run:
        return

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    permits_zip = out_dir / "tfda_permits.zip"
    ingredients_zip = out_dir / "tfda_ingredients.zip"

    log(f"  download permits → {permits_zip.name}")
    n1 = download(PERMITS_URL, permits_zip)
    log(f"    {n1:,} bytes")

    log(f"  download ingredients → {ingredients_zip.name}")
    n2 = download(INGREDIENTS_URL, ingredients_zip)
    log(f"    {n2:,} bytes")

    if not args.no_archive:
        arch_dir = out_dir / "_archive" / today
        arch_dir.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(permits_zip,     arch_dir / permits_zip.name)
        shutil.copy2(ingredients_zip, arch_dir / ingredients_zip.name)
        log(f"  archived snapshot: {arch_dir}")


if __name__ == "__main__":
    main()
