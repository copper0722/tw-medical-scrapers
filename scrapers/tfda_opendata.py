#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""TFDA OpenData scraper (data.fda.gov.tw).

Endpoint pattern (stable, public, no auth):
  https://data.fda.gov.tw/opendata/exportDataList.do?method=ExportData&InfoId=N&logType=3

Returns ZIP containing a single JSON file `N_3.json` (a list of records).

Known InfoIds (extend as needed):
  4   食品標示違規查詢
  36  西藥許可證
  39  藥品仿單或外盒資料集 (許可證字號 → 仿單/外盒圖檔連結)
  40  藥品藥理治療分類AHFS/DI碼資料集 (許可證字號 → AHFS/DI 代碼 crosswalk)
  41  藥品藥理治療分類ATC碼資料集 (許可證字號 → ATC 代碼 crosswalk)
  42  藥品外觀資料集 (許可證字號 → 形狀/顏色/標記/外觀圖檔)
  43  西藥成分
  68  醫療器材許可證
  73  化粧品許可證

InfoId map verified 2026-05-18 by walking data.gov.tw catalog. Earlier doc
claimed 67 for 醫療器材許可證 — that's the human-tissue biobank permit set
(人體生物資料庫設置許可資料); 68 is the correct medical-device permit ID.

Subcommands:
  fetch <info_id>          — download ZIP, extract inner JSON, emit records as JSONL
  list                     — print the known InfoId catalog

Examples:
  uv run scrapers/tfda_opendata.py fetch 36 > tfda-permits.jsonl
  uv run scrapers/tfda_opendata.py fetch 43 --out tfda-ingredients.jsonl
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

UA = "Mozilla/5.0 (tw-medical-scrapers/tfda_opendata)"
BASE = "https://data.fda.gov.tw/opendata/exportDataList.do"
KNOWN_INFOIDS = {
    4:  ("食品標示違規查詢", "食品"),
    36: ("西藥許可證", "西藥"),
    39: ("藥品仿單或外盒資料集", "西藥"),
    40: ("藥品藥理治療分類AHFS/DI碼資料集", "西藥"),
    41: ("藥品藥理治療分類ATC碼資料集", "西藥"),
    42: ("藥品外觀資料集", "西藥"),
    43: ("西藥成分", "西藥"),
    67: ("醫療器材許可證", "醫療器材"),
    73: ("化粧品許可證", "化粧品"),
}


def fetch_zip(info_id: int, log_type: int = 3) -> bytes:
    url = f"{BASE}?method=ExportData&InfoId={info_id}&logType={log_type}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def cmd_list(args) -> None:
    print(f"{'InfoId':6} {'Title':30} Category")
    for iid, (title, cat) in sorted(KNOWN_INFOIDS.items()):
        print(f"{iid:<6} {title:30} {cat}")


def cmd_fetch(args) -> None:
    iid = int(args.info_id)
    print(f"[tfda] fetch InfoId={iid}", file=sys.stderr)
    raw = fetch_zip(iid, log_type=args.log_type)
    print(f"[tfda] zip size={len(raw)} bytes", file=sys.stderr)
    zf = zipfile.ZipFile(io.BytesIO(raw))
    inner = zf.namelist()
    print(f"[tfda] zip contents: {inner}", file=sys.stderr)
    cand = [n for n in inner if n.endswith(".json")] or inner
    if not cand:
        raise RuntimeError(f"no JSON in zip InfoId={iid}: {inner}")
    json_name = cand[0]
    data = json.loads(zf.read(json_name).decode("utf-8"))
    if not isinstance(data, list):
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        else:
            raise RuntimeError(f"unexpected JSON shape InfoId={iid}: {type(data).__name__}")
    print(f"[tfda] {len(data)} records in {json_name}", file=sys.stderr)
    out = sys.stdout if not args.out else open(args.out, "w", encoding="utf-8")
    try:
        for row in data:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    finally:
        if args.out:
            out.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list known InfoIds")
    p_list.set_defaults(func=cmd_list)

    p_fetch = sub.add_parser("fetch", help="download one InfoId, emit records as JSONL")
    p_fetch.add_argument("info_id", help="numeric InfoId (e.g., 36)")
    p_fetch.add_argument("--log-type", type=int, default=3)
    p_fetch.add_argument("--out", default=None, help="JSONL output path (default: stdout)")
    p_fetch.set_defaults(func=cmd_fetch)

    args = ap.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
