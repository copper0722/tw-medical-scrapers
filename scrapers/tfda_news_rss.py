#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# /// script
# requires-python = ">=3.10"
# dependencies = ["cloudscraper"]
# ///
"""
tfda_news_rss.py — Standalone fetcher for 13 TFDA 食藥署 RSS feeds.

Sources (all `https://www.fda.gov.tw/TC/<name>.ashx`):
  rssAnnouncement   公告              doc_type=announcement
  rssLaw            法規              doc_type=regulation
  rssLawAmending    法規修訂           doc_type=regulation
  rssLawMedical     醫療法規           doc_type=regulation
  rssLawFood        食品法規           doc_type=regulation
  rssLawControlled  管制藥品法規        doc_type=regulation
  rssActivity       活動              doc_type=announcement
  rssLawFees        收費規定           doc_type=regulation
  rssLawGGMP        GGMP             doc_type=regulation
  rssLawGTP         GTP              doc_type=regulation
  rssLawLaboratories 實驗室規範        doc_type=regulation
  rssLawMGMP        MGMP             doc_type=regulation
  rssLawTechnology  技術規範           doc_type=regulation

Emits JSONL to stdout or --out (gov-docs ingest contract). Downstream:
_admin-private/.script/import_gov_docs_to_pg.py.
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
from urllib.parse import urlparse, parse_qs

try:
    import cloudscraper
except ImportError:
    print("ERROR: pip3 install cloudscraper", file=sys.stderr)
    sys.exit(1)

BASE = "https://www.fda.gov.tw/TC/"

FEEDS = [
    ("rssAnnouncement.ashx",   "tfda-rss-announcement", "TFDA 公告",       "announcement"),
    ("rssLaw.ashx",            "tfda-rss-law",          "TFDA 法規",       "regulation"),
    ("rssLawAmending.ashx",    "tfda-rss-law-amending", "TFDA 法規修訂",    "regulation"),
    ("rssLawMedical.ashx",     "tfda-rss-law-medical",  "TFDA 醫療法規",    "regulation"),
    ("rssLawFood.ashx",        "tfda-rss-law-food",     "TFDA 食品法規",    "regulation"),
    ("rssLawControlled.ashx",  "tfda-rss-law-controlled", "TFDA 管制藥品法規", "regulation"),
    ("rssActivity.ashx",       "tfda-rss-activity",     "TFDA 活動",        "announcement"),
    ("rssLawFees.ashx",        "tfda-rss-law-fees",     "TFDA 收費規定",    "regulation"),
    ("rssLawGGMP.ashx",        "tfda-rss-law-ggmp",     "TFDA GGMP",       "regulation"),
    ("rssLawGTP.ashx",         "tfda-rss-law-gtp",      "TFDA GTP",        "regulation"),
    ("rssLawLaboratories.ashx","tfda-rss-law-labs",     "TFDA 實驗室規範",  "regulation"),
    ("rssLawMGMP.ashx",        "tfda-rss-law-mgmp",     "TFDA MGMP",       "regulation"),
    ("rssLawTechnology.ashx",  "tfda-rss-law-tech",     "TFDA 技術規範",    "regulation"),
]

REF_RE = re.compile(
    r"((?:衛部|衛署|衛福部|衛福|台食藥|食管|食藥|部授食|部授藥|健保|台財|行政院|國科|教育)"
    r"[一-龥]{0,4}字第\d+[A-Z]?號)"
)


def extract_ref(text: str | None) -> str | None:
    if not text:
        return None
    m = REF_RE.search(text)
    return m.group(1) if m else None


def extract_news_id(url: str) -> str | None:
    """Try `?id=NNNN` or `News_Id=NNNN` query params commonly used on fda.gov.tw."""
    try:
        q = parse_qs(urlparse(url).query)
        for k in ("id", "News_Id", "newsId", "NId"):
            v = q.get(k) or q.get(k.lower())
            if v:
                return str(v[0])
    except Exception:
        pass
    return None


def parse_pub_date(text: str | None) -> str | None:
    if not text:
        return None
    text = text.strip()
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except Exception:
            pass
    return None


def derive_uid(ref: str | None, link: str, listing_id: str, title: str) -> tuple[str, str]:
    if ref:
        return (f"gov:{ref}", "ref_number")
    nid = extract_news_id(link)
    if nid:
        return (f"tfda:{listing_id}-{nid}", "url_id")
    h = hashlib.sha1(f"{title}|{link}".encode("utf-8")).hexdigest()[:12]
    return (f"tfda:{listing_id}-{h}", "title+date")


def fetch_one(scraper, feed_path: str) -> bytes:
    r = scraper.get(BASE + feed_path, timeout=30)
    r.raise_for_status()
    return r.content


def parse_feed(xml_bytes: bytes, listing_id: str, doc_type: str) -> list[dict]:
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        print(f"  parse error on {listing_id}: {e}", file=sys.stderr)
        return items
    for item in root.iterfind(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        pub_date = parse_pub_date(item.findtext("pubDate"))
        ref = extract_ref(title)
        uid, uid_source = derive_uid(ref, link, listing_id, title)
        description = (item.findtext("description") or "").strip()
        items.append({
            "uid": uid,
            "uid_source": uid_source,
            "ref_number": ref,
            "title": title,
            "publisher": "TFDA",
            "doc_type": doc_type,
            "publish_date": pub_date,
            "effective_date": None,
            "source": "tfda_rss",
            "urls": [{
                "url": link,
                "url_source": "rss_link",
                "url_id": extract_news_id(link),
                "source": "tfda_rss",
            }],
            "files": [],
            "content": description if description and description != title else None,
            "tags": [listing_id],
        })
    return items


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--feed", default=None,
                   help="Subset filter: feed-name substring (e.g. 'medical')")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    scraper = cloudscraper.create_scraper()
    feeds = FEEDS if not args.feed else [f for f in FEEDS if args.feed in f[0]]
    if not feeds:
        print(f"no feeds matched {args.feed!r}", file=sys.stderr)
        return 1

    all_items: list[dict] = []
    for feed_path, listing_id, _name, doc_type in feeds:
        try:
            xml_bytes = fetch_one(scraper, feed_path)
            items = parse_feed(xml_bytes, listing_id, doc_type)
        except Exception as e:
            print(f"FAIL {listing_id}: {e}", file=sys.stderr)
            continue
        print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] "
              f"{listing_id}: {len(items)} items", file=sys.stderr)
        all_items.extend(items)

    print(f"total: {len(all_items)} items across {len(feeds)} feed(s)", file=sys.stderr)

    if args.dry_run:
        for it in all_items[:3]:
            print(f"  sample: {it['uid']}  {it['title'][:60]}", file=sys.stderr)
        return 0

    if args.out:
        with args.out.open("w", encoding="utf-8") as f:
            for it in all_items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
        print(f"wrote {len(all_items)} rows → {args.out}", file=sys.stderr)
    else:
        for it in all_items:
            print(json.dumps(it, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
