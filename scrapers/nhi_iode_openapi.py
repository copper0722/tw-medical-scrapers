#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""NHI IODE OpenAPI scraper.

Source: NHI 開放資料平台 (info.nhi.gov.tw/IODE0000), official OpenAPI 3.0
spec at info.nhi.gov.tw/IODE0000/openapi.json (Taiwan Government Open
Data License v1, free, no auth).

Subcommands:
  catalog                 — discover all 350 datasets via SPA SQL008_1
                            (the canonical universe; OpenAPI /dataset
                            endpoint is partial)
  dataset <identifier>    — full metadata via OpenAPI /dataset/{identifier}
  datastore <resource_id> — paginated records via /datastore/{resource_id};
                            handles --all to fetch every page
  download <resource_id>  — direct CSV/JSON/XML full download via the
                            distribution[].downloadURL or
                            /dataset/{resource_id}?format=

Output:
  JSONL one record per line, stdout or --out file. No PG writes, no DB
  state. Idempotent re-run safe.

Examples:
  uv run scrapers/nhi_iode_openapi.py catalog > catalog.jsonl
  uv run scrapers/nhi_iode_openapi.py dataset A21030000I-E41001 > drug-meta.json
  uv run scrapers/nhi_iode_openapi.py datastore A21030000I-E41001-001 --all > drug-records.jsonl
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

SPA_API = "https://info.nhi.gov.tw/api/iode0000s01"     # SPA backend (catalog discovery)
OPENAPI = "https://info.nhi.gov.tw/api/iode0010/v1/rest"  # official OpenAPI 3.0
UA = "Mozilla/5.0 (tw-medical-scrapers/nhi_iode_openapi)"

# info.nhi.gov.tw cert chain is missing Subject Key Identifier (gov.tw
# legacy chain); curl tolerates it by default but Python urllib does
# strict verification. Use an unverified context for this single host
# since the content is a public open-data API anyway.
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def fetch_json(url: str, retries: int = 3, sleep_s: float = 2.0) -> dict | list:
    """GET URL, return parsed JSON. Retries on transient errors."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as r:
                return json.loads(r.read())
        except Exception as e:
            last = e
            if attempt < retries - 1:
                time.sleep(sleep_s * (attempt + 1))
    raise RuntimeError(f"fetch_json failed for {url}: {last}")


def cmd_catalog(args) -> None:
    """List all 350 datasets via SPA SQL008_1."""
    payload = fetch_json(f"{SPA_API}/SQL008_1?searchType=all")
    data = payload.get("data", []) if isinstance(payload, dict) else []
    if not data:
        print(f"[catalog] no data returned", file=sys.stderr)
        return
    print(f"[catalog] {len(data)} datasets", file=sys.stderr)
    out = sys.stdout if not args.out else open(args.out, "w", encoding="utf-8")
    try:
        for row in data:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    finally:
        if args.out:
            out.close()


def cmd_dataset(args) -> None:
    """Full metadata for one dataset identifier."""
    payload = fetch_json(f"{OPENAPI}/dataset/{urllib.parse.quote(args.identifier)}")
    text = json.dumps(payload, ensure_ascii=False, indent=None if args.compact else 2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)


def cmd_datastore(args) -> None:
    """Paginated records via /datastore/{resource_id}."""
    rid = args.resource_id
    page_limit = max(1, min(args.page_limit, 1000))
    offset = 0
    n_emitted = 0
    out = sys.stdout if not args.out else open(args.out, "w", encoding="utf-8")
    try:
        while True:
            url = f"{OPENAPI}/datastore/{urllib.parse.quote(rid)}?limit={page_limit}&offset={offset}"
            payload = fetch_json(url)
            records = payload.get("result", {}).get("records", []) if isinstance(payload, dict) else []
            if not records:
                break
            for r in records:
                out.write(json.dumps(r, ensure_ascii=False) + "\n")
            n_emitted += len(records)
            print(f"[datastore] {rid} offset={offset} got={len(records)} total={n_emitted}",
                  file=sys.stderr)
            if not args.all or len(records) < page_limit:
                break
            offset += len(records)
            if args.max_records and n_emitted >= args.max_records:
                break
    finally:
        if args.out:
            out.close()
    print(f"[datastore] done: {n_emitted} records", file=sys.stderr)


def cmd_download(args) -> None:
    """Download full resource as one file (JSON/CSV/XML)."""
    fmt = args.format.upper()
    url = f"{OPENAPI}/dataset/{urllib.parse.quote(args.resource_id)}?format={fmt}"
    out_path = Path(args.out) if args.out else Path(f"{args.resource_id}.{fmt.lower()}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300, context=SSL_CTX) as r, open(out_path, "wb") as f:
        while True:
            chunk = r.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)
    print(f"[download] saved {out_path} ({out_path.stat().st_size} bytes)", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_cat = sub.add_parser("catalog", help="list all datasets via SPA SQL008_1")
    p_cat.add_argument("--out", default=None, help="output JSONL path")
    p_cat.set_defaults(func=cmd_catalog)

    p_ds = sub.add_parser("dataset", help="full metadata for one identifier")
    p_ds.add_argument("identifier")
    p_ds.add_argument("--out", default=None)
    p_ds.add_argument("--compact", action="store_true")
    p_ds.set_defaults(func=cmd_dataset)

    p_st = sub.add_parser("datastore", help="paginated records")
    p_st.add_argument("resource_id")
    p_st.add_argument("--all", action="store_true", help="fetch every page")
    p_st.add_argument("--page-limit", type=int, default=1000, help="records per page (max 1000)")
    p_st.add_argument("--max-records", type=int, default=0, help="cap total records (0 = no cap)")
    p_st.add_argument("--out", default=None)
    p_st.set_defaults(func=cmd_datastore)

    p_dl = sub.add_parser("download", help="download full resource as one file")
    p_dl.add_argument("resource_id")
    p_dl.add_argument("--format", default="JSON", help="JSON / CSV / XML (default JSON)")
    p_dl.add_argument("--out", default=None)
    p_dl.set_defaults(func=cmd_download)

    args = ap.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
