#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
pubmed_image_backfill.py — Re-fetch images for PubMed articles already staged
by pubmed_oa_hd_reviews.py.

Use case: an earlier fetch with a wrong URL pattern (e.g. www.ncbi.nlm.nih.gov
/pmc/articles/PMC{id}/bin/{href} returns 404 instead of pmc.ncbi.nlm.nih.gov
/articles/instance/{id}/bin/{href}) marked all images as unfetched. This script
walks the existing index.jsonl, retries each unfetched image with the corrected
URL, and updates the manifest in place.

Idempotent: skips images already fetched (local file exists with non-zero size).

Usage:
  uv run pubmed_image_backfill.py /path/to/_staging/pubmed/<batch>/
  uv run pubmed_image_backfill.py /path/to/_staging/pubmed/<batch>/ --rate 5

Run on a binary-capable host (per LAW: hm4 / mbp; NOT cm1 / mba ~/repos/*).
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

USER_AGENT = "tw-medical-scrapers/pubmed_image_backfill"


def correct_url(pmc_id: str, href: str) -> str:
    """The correct PMC image URL pattern (verified 2026-05-08)."""
    suffix = "" if "." in href else ".jpg"
    return f"https://pmc.ncbi.nlm.nih.gov/articles/instance/{pmc_id}/bin/{href}{suffix}"


def fetch(url: str, dest: Path) -> tuple[bool, str]:
    if dest.exists() and dest.stat().st_size > 0:
        return (True, "exists")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return (True, f"fetched {len(data)} bytes")
    except Exception as e:
        return (False, str(e))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("staging_dir", type=Path,
                   help="Path to a staging batch dir (containing index.jsonl + per-article folders)")
    p.add_argument("--rate", type=float, default=5.0,
                   help="Max images per second (default 5)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    idx = args.staging_dir / "index.jsonl"
    if not idx.exists():
        print(f"no index.jsonl at {idx}", file=sys.stderr)
        return 2

    rows = [json.loads(l) for l in idx.read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"[backfill] {len(rows)} articles in {args.staging_dir}", file=sys.stderr)

    min_gap = 1.0 / args.rate
    last = 0.0
    n_articles = n_fetched = n_skipped = n_failed = 0

    new_rows: list[dict] = []
    for m in rows:
        n_articles += 1
        pmc_id = m.get("pmc_id")
        images = m.get("images") or []
        if not pmc_id or not images:
            new_rows.append(m)
            continue
        cite = m["citation_key"]
        article_dir = args.staging_dir / cite
        for im in images:
            href = im.get("href")
            if not href:
                continue
            fname = href if "." in href else href + ".jpg"
            fname = re.sub(r"[^A-Za-z0-9._-]", "_", fname)
            local = article_dir / "images" / fname
            if im.get("fetched") and im.get("local_path") and Path(im["local_path"]).exists():
                n_skipped += 1
                continue
            new_url = correct_url(pmc_id, href)
            if args.dry_run:
                print(f"  [dry] {cite}/{fname} → {new_url}", file=sys.stderr)
                continue
            now = time.monotonic()
            gap = now - last
            if gap < min_gap:
                time.sleep(min_gap - gap)
            ok, msg = fetch(new_url, local)
            last = time.monotonic()
            if ok:
                n_fetched += 1
                im["url"] = new_url
                im["local_path"] = str(local)
                im["local_filename"] = fname
                im["fetched"] = True
            else:
                n_failed += 1
                im["url"] = new_url  # at least record corrected URL
                im["fetched"] = False
                im["last_fetch_error"] = msg
            print(f"  {'✓' if ok else '✗'} {cite}/{fname}: {msg}", file=sys.stderr)
        # rewrite article manifest in place
        m["images_fetched"] = sum(1 for i in m["images"] if i.get("fetched"))
        m["images_total"] = len(m["images"])
        if not args.dry_run:
            (article_dir / "manifest.json").write_text(
                json.dumps(m, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        new_rows.append(m)

    if not args.dry_run:
        idx.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in new_rows) + "\n",
                       encoding="utf-8")

    print(f"[done] articles={n_articles}  fetched={n_fetched}  "
          f"skipped(already_local)={n_skipped}  failed={n_failed}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
