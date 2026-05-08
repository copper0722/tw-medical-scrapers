#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# /// script
# requires-python = ">=3.10"
# dependencies = ["cloudscraper"]
# ///
"""
nhi_regulation_rss.py — Standalone fetcher for NHI 法規公告 RSS (lp-3258).

Source: https://www.nhi.gov.tw/ch/rss-3258-1.xml  (Cloudflare-protected)

Emits JSONL (one row per RSS item) on stdout (default) or to `--out` file. The schema
matches the gov-docs ingest contract; downstream the private side
(_admin-private/.script/import_gov_docs_to_pg.py) consumes this JSONL and UPSERTs into
hmj.tw_gov_docs.

Per tw-medical-scrapers AGENTS.md rules: standalone (PEP 723), no DB writes here, no
shared internal modules. Public-data only.

Usage:
  uv run nhi_regulation_rss.py                          # stdout
  uv run nhi_regulation_rss.py --out items.jsonl
  python3 nhi_regulation_rss.py --dry-run               # fetch + parse, print count, no JSONL emit
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

try:
    import cloudscraper
except ImportError:
    print("ERROR: pip3 install cloudscraper", file=sys.stderr)
    sys.exit(1)

RSS_URL = "https://www.nhi.gov.tw/ch/rss-3258-1.xml"
LISTING_LABEL = "rss-3258"  # NHI 法規公告 RSS feed identifier

REF_PATTERNS = [
    re.compile(r"健保[^\s]*?字第\s*\d+\s*號"),       # 健保醫字第XXX號 / 健保藥字第XXX號 / etc.
    re.compile(r"衛部[^\s]*?字第\s*\d+\s*號"),       # 衛部醫字第XXX號
    re.compile(r"部授[^\s]*?字第\s*\d+\s*號"),       # 部授國字第XXX號
]


def extract_ref_number(title: str) -> str | None:
    for pat in REF_PATTERNS:
        m = pat.search(title)
        if m:
            return re.sub(r"\s+", "", m.group(0))
    return None


def parse_pub_date(text: str | None) -> str | None:
    """RSS pubDate → YYYY-MM-DD (date only)."""
    if not text:
        return None
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(text.strip(), fmt).date().isoformat()
        except Exception:
            continue
    return None


def derive_uid(ref_number: str | None, link: str, title: str, pub_date: str | None) -> tuple[str, str]:
    """Returns (uid, uid_source). Prefer ref_number; fall back to URL id; fall back to title+date hash."""
    if ref_number:
        return (f"gov:{ref_number}", "ref_number")
    # try URL id pattern: cp-XXXXX or sp-XXXXX or numeric
    m = re.search(r"(cp|sp|np)-(\d+)", link)
    if m:
        return (f"nhi:{m.group(0)}", "url_id")
    # last resort: deterministic hash of title+date
    seed = f"{title}|{pub_date or ''}|{link}"
    h = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return (f"nhi:rss-3258-{h}", "title+date")


def fetch_xml() -> bytes:
    s = cloudscraper.create_scraper()
    r = s.get(RSS_URL, timeout=30)
    r.raise_for_status()
    return r.content


def parse(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    items = []
    # RSS 2.0: channel/item
    for item in root.iterfind(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date_raw = item.findtext("pubDate") or item.findtext("{http://purl.org/dc/elements/1.1/}date")
        guid = (item.findtext("guid") or link or title).strip()
        description = (item.findtext("description") or "").strip()
        if not title or not link:
            continue
        pub_date = parse_pub_date(pub_date_raw)
        ref_number = extract_ref_number(title)
        uid, uid_source = derive_uid(ref_number, link, title, pub_date)
        items.append({
            "uid": uid,
            "uid_source": uid_source,
            "ref_number": ref_number,
            "title": title,
            "publisher": "NHI",
            "doc_type": "regulation",
            "publish_date": pub_date,
            "effective_date": None,
            "source": "rss_scraper",
            "urls": [{
                "url": link,
                "url_source": "rss_link",
                "url_id": guid if guid != link else None,
                "source": "rss_scraper",
            }],
            "files": [],
            "content": description if description and description != title else None,
            "tags": [],
        })
    return items


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=None,
                   help="Output JSONL file (default: stdout)")
    p.add_argument("--dry-run", action="store_true",
                   help="Fetch + parse + print summary, do not emit JSONL")
    args = p.parse_args()

    try:
        xml_bytes = fetch_xml()
    except Exception as e:
        print(f"FETCH FAIL: {e}", file=sys.stderr)
        return 2

    items = parse(xml_bytes)
    print(f"[{datetime.now(timezone.utc).isoformat()}] fetched {len(items)} items from {RSS_URL}",
          file=sys.stderr)

    if args.dry_run:
        for it in items[:3]:
            print(f"  sample: {it['uid']}  {it['title'][:60]}", file=sys.stderr)
        return 0

    out = args.out
    if out:
        with out.open("w", encoding="utf-8") as f:
            for it in items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
        print(f"wrote {len(items)} rows → {out}", file=sys.stderr)
    else:
        for it in items:
            print(json.dumps(it, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
