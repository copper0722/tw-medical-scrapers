#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""TFDA medical device label/IFU URL scraper (OpenData InfoId 70).

Endpoint (public, no auth):
  https://data.fda.gov.tw/opendata/exportDataList.do?method=ExportData&InfoId=70&logType=3

Returns a ZIP containing one JSON file. Each record is TFDA's classic
`[{key:value}, {key:value}, ...]` list-of-singletons shape; this scraper
flattens + projects to a stable 8-key schema with extracted UUIDs:

  {
    "permit_no":      "衛部醫器陸輸字第000964號",
    "name_zh":        "「河南駝人」氣管內管",
    "name_en":        "\"Henan Tuoren\" Endotracheal Tube",
    "label_url":      "https://lmspiq.fda.gov.tw/api/public/storage/download/<UUID>",
    "package_url":    "https://lmspiq.fda.gov.tw/api/public/storage/download/<UUID>",
    "label_uuid":     "<UUID>",
    "package_uuid":   "<UUID>",
    "source_info_id": 70
  }

Coverage caveat (verified 2026-05-25, 39,146 records):

  輸     28,779  (Class II import)
  製      7,909  (Class II domestic)
  陸輸    1,876  (Class II China-import)
  輸壹      368  (Class I import)
  製壹      201  (Class I domestic)
  陸輸壹     12  (Class I China-import) ← very sparse

Class I devices (lic format ...壹字第...) are rarely uploaded since TFDA
does not mandate digital IFU for Class I. If you need a Class I IFU,
contact the importer/manufacturer directly.

PDF/image binaries themselves are NOT fetched here (CLAUDE.md: binary
crawl + extraction belongs to wiki_raw, not this repo). The downloadable
URLs are emitted as-is for downstream consumers (PG ingest, wiki_raw
binary pipeline) to handle as appropriate.

Subcommands:
  fetch       — download InfoId 70, normalize, emit one JSON record per line
  lookup      — given permit_no(s), filter a fetched JSONL

Examples:
  uv run scrapers/tfda_device_label.py fetch --out tfda-device-labels.jsonl
  uv run scrapers/tfda_device_label.py lookup \\
      --input tfda-device-labels.jsonl \\
      "衛部醫器陸輸字第000964號"
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

UA = "Mozilla/5.0 (tw-medical-scrapers/tfda_device_label)"
INFO_ID = 70
BASE = "https://data.fda.gov.tw/opendata/exportDataList.do"
UUID_RE = re.compile(r"/download/([0-9A-Fa-f][0-9A-Fa-f-]{34,})")


def fetch_zip() -> bytes:
    url = f"{BASE}?method=ExportData&InfoId={INFO_ID}&logType=3"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def extract_uuid(url: str | None) -> str | None:
    if not url:
        return None
    m = UUID_RE.search(url)
    return m.group(1) if m else None


def normalize(rec: list) -> dict:
    flat: dict = {}
    for d in rec:
        if isinstance(d, dict):
            flat.update(d)
    return {
        "permit_no": (flat.get("許可證字號") or "").strip(),
        "name_zh": flat.get("中文品名"),
        "name_en": flat.get("英文品名"),
        "label_url": flat.get("說明書圖檔連結"),
        "package_url": flat.get("包裝圖檔連結"),
        "label_uuid": extract_uuid(flat.get("說明書圖檔連結")),
        "package_uuid": extract_uuid(flat.get("包裝圖檔連結")),
        "source_info_id": INFO_ID,
    }


def cmd_fetch(args) -> None:
    print(f"[tfda] fetch InfoId={INFO_ID} (醫療器材說明書圖檔連結)", file=sys.stderr)
    raw = fetch_zip()
    print(f"[tfda] zip size={len(raw)} bytes", file=sys.stderr)
    zf = zipfile.ZipFile(io.BytesIO(raw))
    inner = zf.namelist()
    cand = [n for n in inner if n.endswith(".json")] or inner
    if not cand:
        raise RuntimeError(f"no JSON in zip: {inner}")
    data = json.loads(zf.read(cand[0]).decode("utf-8"))
    if not isinstance(data, list):
        raise RuntimeError(f"unexpected JSON shape: {type(data).__name__}")
    print(f"[tfda] {len(data)} raw records in {cand[0]}", file=sys.stderr)

    out = sys.stdout if not args.out else open(args.out, "w", encoding="utf-8")
    seen: set[str] = set()
    written = 0
    skipped_empty = 0
    skipped_dup = 0
    try:
        for rec in data:
            row = normalize(rec)
            if not row["permit_no"]:
                skipped_empty += 1
                continue
            if row["permit_no"] in seen:
                skipped_dup += 1
                continue
            seen.add(row["permit_no"])
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            written += 1
    finally:
        if args.out:
            out.close()
    print(
        f"[tfda] wrote {written} unique permits "
        f"(skipped {skipped_empty} empty permit_no, {skipped_dup} dup)",
        file=sys.stderr,
    )


def cmd_lookup(args) -> None:
    path = Path(args.input)
    if not path.exists():
        sys.exit(f"input not found: {path}")
    needles = set(args.permit_no)
    found = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row["permit_no"] in needles:
                found.append(row)
    if not found:
        sys.exit(f"no records found for {needles}")
    for row in found:
        print(json.dumps(row, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser("fetch", help="download InfoId 70, emit normalized JSONL")
    p_fetch.add_argument("--out", default=None, help="JSONL output path (default: stdout)")
    p_fetch.set_defaults(func=cmd_fetch)

    p_lookup = sub.add_parser("lookup", help="filter a fetched JSONL by permit_no")
    p_lookup.add_argument("--input", required=True, help="JSONL path emitted by fetch")
    p_lookup.add_argument("permit_no", nargs="+", help="one or more 許可證字號")
    p_lookup.set_defaults(func=cmd_lookup)

    args = ap.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
