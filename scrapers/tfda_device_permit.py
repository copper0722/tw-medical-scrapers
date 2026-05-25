#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""TFDA medical device permit scraper (OpenData InfoId 68).

Endpoint (public, no auth):
  https://data.fda.gov.tw/opendata/exportDataList.do?method=ExportData&InfoId=68&logType=3

InfoId 68 contains ~103,648 records (verified 2026-05-25) — every medical
device permit issued by TFDA. Sister dataset InfoId 70 (label/IFU URLs)
covers the (mostly Class II/III) permits with uploaded digital IFU; this
scraper covers full permit metadata for all classes.

This scraper flattens TFDA's `[{key:value}, ...]` list-of-singletons into
a stable flat dict with 34 keys (one row per permit). Date columns stay
as raw TEXT (TFDA returns AD year `YYYY/MM/DD`; some are blank).

Coverage notes:

  permit_kind distribution (sampled 2026-05-25):
    09  ~95%   醫療器材
    others    (cosmetics / surgical mask emergency permits / etc.)

  device_class:
    1   Class I (low risk; lic format ...壹字第NNN號)
    2   Class II (moderate risk; lic format ...字第NNN號)
    3   Class III (high risk)

PDF binaries (IFU, packaging images) are NOT fetched here — IFU URLs are
in the sister InfoId 70 dataset (see tfda_device_label.py). Per
CLAUDE.md: binary crawl + extraction belongs to wiki_raw, not this repo.

Subcommands:
  fetch       — download InfoId 68, normalize, emit one JSON record per line
  lookup      — given permit_no(s), filter a fetched JSONL

Examples:
  uv run scrapers/tfda_device_permit.py fetch --out tfda-device-permits.jsonl
  uv run scrapers/tfda_device_permit.py lookup --input tfda-device-permits.jsonl 衛部醫器陸輸壹字第002796號
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

UA = "Mozilla/5.0 (tw-medical-scrapers/tfda_device_permit)"
INFO_ID = 68
BASE = "https://data.fda.gov.tw/opendata/exportDataList.do"

# TFDA JSON field → flat dict key (snake_case English).
FIELD_MAP: dict[str, str] = {
    "許可證字號": "permit_no",
    "註銷狀態": "cancellation_status",
    "註銷日期": "cancellation_date",
    "註銷理由": "cancellation_reason",
    "有效日期": "valid_until",
    "發證日期": "issue_date",
    "許可證種類": "permit_kind",
    "舊證字號": "old_permit_no",
    "醫療器材級數": "device_class",
    "通關簽審文件編號": "customs_doc_no",
    "中文品名": "name_zh",
    "英文品名": "name_en",
    "效能": "indication",
    "劑型": "dosage_form",
    "包裝": "packaging",
    "醫器主類別一": "cat_main_1",
    "醫器次類別一": "cat_sub_1",
    "醫器主類別二": "cat_main_2",
    "醫器次類別二": "cat_sub_2",
    "醫器主類別三": "cat_main_3",
    "醫器次類別三": "cat_sub_3",
    "主成分略述": "active_ingredient",
    "醫器規格": "device_spec",
    "限制項目": "restrictions",
    "申請商名稱": "applicant_name",
    "申請商地址": "applicant_addr",
    "申請商統一編號": "applicant_id",
    "製造商名稱": "mfr_name",
    "製造廠廠址": "mfr_addr",
    "製造廠公司地址": "mfr_company_addr",
    "製造廠國別": "mfr_country",
    "製程": "process",
    "異動日期": "change_date",
    "製造許可登錄編號": "manufacturing_permit_no",
}


def fetch_zip() -> bytes:
    url = f"{BASE}?method=ExportData&InfoId={INFO_ID}&logType=3"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.read()


def normalize(rec: list) -> dict:
    flat: dict = {}
    for d in rec:
        if isinstance(d, dict):
            flat.update(d)
    out: dict = {}
    for zh_key, en_key in FIELD_MAP.items():
        val = flat.get(zh_key)
        if isinstance(val, str):
            val = val.strip() or None
        out[en_key] = val
    # device_class → int (1/2/3), or None if blank/invalid
    dc = out.get("device_class")
    if dc and isinstance(dc, str) and dc.strip().isdigit():
        out["device_class"] = int(dc.strip())
    elif dc and isinstance(dc, int):
        pass
    else:
        out["device_class"] = None
    out["source_info_id"] = INFO_ID
    return out


def cmd_fetch(args) -> None:
    print(f"[tfda] fetch InfoId={INFO_ID} (醫療器材許可證 metadata)", file=sys.stderr)
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
            permit = row.get("permit_no")
            if not permit:
                skipped_empty += 1
                continue
            if permit in seen:
                skipped_dup += 1
                continue
            seen.add(permit)
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
            if row.get("permit_no") in needles:
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

    p_fetch = sub.add_parser("fetch", help="download InfoId 68, emit normalized JSONL")
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
