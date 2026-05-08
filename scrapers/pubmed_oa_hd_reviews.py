#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
pubmed_oa_hd_reviews.py — Standalone PubMed Open-Access fetcher for hemodialysis
narrative reviews / opinions / viewpoints / expert opinions / editorials.

Pipeline:
  1. esearch  → list PMIDs matching the curated filter (MeSH + pub-type + OA + date)
  2. esummary → per-PMID metadata (title, authors, journal, pub_date, DOI, PMC_id)
  3. efetch (db=pmc, rettype=xml) for any article with PMC_id → JATS XML full text
  4. JATS → clean markdown (section headings + paragraphs + tables; refs preserved)
  5. Per-article output to <out>/{citation_key}/{raw.md, manifest.json}
     + global <out>/index.jsonl  (one line per article = source-of-truth for downstream
     PG ingest into wiki_raw.journal_article_sources etc)

`citation_key` shape: `{first_author_lastname}{year}_{journal_abbrev}_{pmid}`
e.g. `Smith2024_AmJKidneyDis_38123456`. Slug-safe; deterministic.

Per tw-medical-scrapers AGENTS.md rules: standalone (PEP 723), no DB writes, all
output under --out (user-specified). No PDF download, no MinerU; full text comes
from PMC JATS XML (already structured). PDF binary extraction belongs to wiki_raw.

Usage:
  uv run pubmed_oa_hd_reviews.py --dry-run                # esearch only, print count
  uv run pubmed_oa_hd_reviews.py --since 2024-05-08 --out /tmp/pubmed-hd/
  uv run pubmed_oa_hd_reviews.py --pmid 38123456 --out /tmp/pubmed-hd/
                                                          # single-PMID test mode
  uv run pubmed_oa_hd_reviews.py --since 2024-05-08 --out /tmp/pubmed-hd/ --limit 5
                                                          # cap fetch for first run

Environment (optional):
  NCBI_API_KEY    — bumps rate limit 3/s → 10/s
  NCBI_EMAIL      — used in NCBI tool params (default copper.wang@gmail.com)
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
EMAIL = os.environ.get("NCBI_EMAIL", "copper.wang@gmail.com")
API_KEY = os.environ.get("NCBI_API_KEY")
TOOL = "tw-medical-scrapers/pubmed_oa_hd_reviews"

# PubMed E-utilities query.
# Copper directive 2026-05-08: narrative review / opinion / viewpoint / expert
# opinion / CME / editorial only — NOT systematic review or meta-analysis (those
# are original-research synthesis, different consumption).
#
# PubMed has no `narrative review` pub-type → use title heuristic. Pub types kept
# from NCBI canonical list: editorial[pt], comment[pt]. Excluded:
# `Systematic Review[pt]`, `Meta-Analysis[pt]`, generic `Review[pt]` (too broad).
#
# OA: loattrfree full text[sb] (PMC OA filter).
QUERY_TEMPLATE = (
    '("Renal Dialysis"[MeSH] OR hemodialysis[ti] OR dialysis[ti])'
    ' AND ('
    '"narrative review"[ti]'
    ' OR "viewpoint"[ti]'
    ' OR "expert opinion"[ti]'
    ' OR "perspective"[ti]'
    ' OR "commentary"[ti]'
    ' OR "opinion"[ti]'
    ' OR "CME"[ti]'
    ' OR editorial[pt]'
    ' OR comment[pt]'
    ')'
    ' NOT ("Systematic Review"[pt] OR "Meta-Analysis"[pt])'
    ' AND "loattrfree full text"[sb]'
    ' AND ("{since}"[Date - Publication] : "{until}"[Date - Publication])'
)


class RateLimiter:
    """Simple per-process throttle. NCBI: 3/s without key, 10/s with key."""
    def __init__(self, per_second: float):
        self.min_gap = 1.0 / per_second
        self.last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        gap = now - self.last
        if gap < self.min_gap:
            time.sleep(self.min_gap - gap)
        self.last = time.monotonic()


def make_url(endpoint: str, **params) -> str:
    base = {"tool": TOOL, "email": EMAIL}
    if API_KEY:
        base["api_key"] = API_KEY
    base.update(params)
    return f"{EUTILS}/{endpoint}.fcgi?{urllib.parse.urlencode(base)}"


def http_get(url: str, retries: int = 3) -> bytes:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": TOOL})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(1 + attempt * 2)
    raise RuntimeError(f"http_get failed after {retries}: {last_err}")


def esearch(query: str, retmax: int, throttle: RateLimiter) -> tuple[int, list[str]]:
    """Return (total_count, pmids[:retmax])."""
    throttle.wait()
    raw = http_get(make_url(
        "esearch",
        db="pubmed", term=query, retmode="xml", retmax=str(retmax),
        sort="pub_date",
    ))
    root = ET.fromstring(raw)
    count = int(root.findtext("Count", "0"))
    pmids = [el.text for el in root.iterfind(".//IdList/Id") if el.text]
    return count, pmids


def esummary(pmids: list[str], throttle: RateLimiter) -> list[dict]:
    """Return per-PMID metadata dicts."""
    if not pmids:
        return []
    throttle.wait()
    raw = http_get(make_url(
        "esummary",
        db="pubmed", id=",".join(pmids), retmode="xml",
    ))
    root = ET.fromstring(raw)
    out = []
    for doc in root.iterfind(".//DocSum"):
        rec = {"pmid": doc.findtext("Id")}
        for item in doc.iterfind("./Item"):
            name = item.get("Name")
            if name == "Title":
                rec["title"] = (item.text or "").strip()
            elif name == "Source":
                rec["journal"] = (item.text or "").strip()
            elif name == "PubDate":
                rec["pub_date_raw"] = (item.text or "").strip()
            elif name == "EPubDate":
                rec["epub_date"] = (item.text or "").strip()
            elif name == "AuthorList":
                rec["authors"] = [
                    (a.text or "").strip() for a in item.iterfind("./Item[@Name='Author']")
                ]
            elif name == "PubTypeList":
                rec["pub_types"] = [
                    (p.text or "").strip() for p in item.iterfind("./Item[@Name='PubType']")
                ]
            elif name == "ArticleIds":
                ids = {}
                for sub in item.iterfind("./Item"):
                    n = sub.get("Name")
                    if n in ("doi", "pmc", "pmcid"):
                        ids[n] = (sub.text or "").strip()
                rec["doi"] = ids.get("doi")
                # pmc / pmcid both used by NCBI; normalise
                pmc = ids.get("pmc") or ids.get("pmcid")
                if pmc:
                    rec["pmc_id"] = pmc.replace("PMC", "")
        out.append(rec)
    return out


def efetch_pmc_xml(pmc_id: str, throttle: RateLimiter) -> str | None:
    throttle.wait()
    try:
        raw = http_get(make_url(
            "efetch",
            db="pmc", id=pmc_id, rettype="xml", retmode="xml",
        ))
        return raw.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  efetch pmc:{pmc_id} failed: {e}", file=sys.stderr)
        return None


def extract_image_refs(xml_str: str, pmc_id: str) -> list[dict]:
    """Walk JATS XML for <graphic> + <inline-graphic> elements; resolve to PMC bin URL.

    PMC OA images live at https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{id}/bin/{href}.
    Returns: [{href, url, caption, kind: 'fig'|'inline-graphic'|'table-graphic'}]
    """
    if not xml_str:
        return []
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    # JATS uses xlink namespace for href
    XLINK = "{http://www.w3.org/1999/xlink}href"
    for parent_tag, kind in (("fig", "fig"), ("table-wrap", "table-graphic"),
                             ("inline-graphic", "inline-graphic")):
        # iterate all matching parents
        for parent in root.iter():
            ptag = parent.tag.split("}", 1)[-1]
            if ptag != parent_tag:
                continue
            # find <graphic> inside (or self if parent IS inline-graphic)
            cands = [parent] if parent_tag == "inline-graphic" else list(
                e for e in parent.iter() if e.tag.split("}", 1)[-1] == "graphic"
            )
            for g in cands:
                href = g.get(XLINK) or g.get("href") or ""
                if not href or href in seen:
                    continue
                seen.add(href)
                # Caption: parent may have <caption><p>...
                cap = ""
                if parent_tag != "inline-graphic":
                    cap_el = parent.find(".//caption")
                    if cap_el is not None:
                        cap = _render_inline(cap_el).strip()
                    if not cap:
                        label = parent.find("./label")
                        if label is not None:
                            cap = _render_inline(label).strip()
                # Correct PMC bin URL pattern (verified 2026-05-08):
                #   https://pmc.ncbi.nlm.nih.gov/articles/instance/{numeric_id}/bin/{href}
                # 301-redirects to CDN hashed URL; urllib.request follows by default.
                # Old `www.ncbi.nlm.nih.gov/pmc/articles/PMC{id}/bin/...` returns 404.
                url = (
                    f"https://pmc.ncbi.nlm.nih.gov/articles/instance/{pmc_id}/bin/"
                    f"{href}{'' if '.' in href else '.jpg'}"
                )
                out.append({"href": href, "url": url, "caption": cap, "kind": kind})
    return out


def fetch_image(url: str, dest: Path, throttle: RateLimiter) -> bool:
    """Download image binary to dest. Returns True on success."""
    if dest.exists() and dest.stat().st_size > 0:
        return True
    throttle.wait()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": TOOL})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return True
    except Exception as e:
        print(f"    image fetch fail {url}: {e}", file=sys.stderr)
        return False


def jats_to_markdown(xml_str: str) -> str:
    """Strip JATS XML to clean markdown. Keep section headers + paragraphs + tables.

    Not a full JATS renderer; targets the 80% case for OA biomed articles.
    Falls back on plain-text extraction for unrecognised tags.
    """
    try:
        # JATS files have a <pmc-articleset><article>... wrapper
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return ""
    article = root.find(".//article") or root

    out: list[str] = []

    front = article.find(".//front")
    if front is not None:
        title = front.findtext(".//article-title")
        if title:
            out.append(f"# {title.strip()}")
        # journal + year
        journal = front.findtext(".//journal-title")
        year = front.findtext(".//pub-date/year") or front.findtext(".//pub-date//year")
        if journal:
            line = f"_{journal.strip()}"
            if year:
                line += f", {year.strip()}"
            line += "_"
            out.append(line)
        # abstract
        abs_el = front.find(".//abstract")
        if abs_el is not None:
            out.append("\n## Abstract\n")
            out.append(_render_section_body(abs_el))

    body = article.find(".//body")
    if body is not None:
        for sec in body.iterfind("./sec"):
            out.extend(_render_section(sec, depth=2))
        # any orphan paragraphs not in <sec>
        for p in body.iterfind("./p"):
            txt = _render_inline(p).strip()
            if txt:
                out.append(txt + "\n")

    back = article.find(".//back")
    if back is not None:
        ref_list = back.find(".//ref-list")
        if ref_list is not None:
            out.append("\n## References\n")
            for i, ref in enumerate(ref_list.iterfind("./ref"), 1):
                text = _render_inline(ref).strip()
                if text:
                    out.append(f"{i}. {text}")

    return "\n\n".join(out).strip() + "\n"


def _render_section(sec: ET.Element, depth: int) -> list[str]:
    out: list[str] = []
    title = sec.find("./title")
    if title is not None:
        t = _render_inline(title).strip()
        if t:
            out.append(f"\n{'#' * min(depth, 6)} {t}\n")
    out.append(_render_section_body(sec))
    for child_sec in sec.iterfind("./sec"):
        out.extend(_render_section(child_sec, depth=depth + 1))
    return out


def _render_section_body(sec: ET.Element) -> str:
    parts: list[str] = []
    for child in sec:
        tag = child.tag.split("}", 1)[-1]  # strip {namespace}
        if tag in ("title",):
            continue
        if tag == "p":
            parts.append(_render_inline(child).strip())
        elif tag == "list":
            for li in child.iterfind("./list-item"):
                parts.append("- " + _render_inline(li).strip())
        elif tag in ("table-wrap", "fig"):
            cap = child.findtext(".//caption//p") or child.findtext(".//label") or ""
            if cap.strip():
                parts.append(f"_{tag}: {cap.strip()}_")
        elif tag == "sec":
            continue  # handled by caller
        else:
            parts.append(_render_inline(child).strip())
    return "\n\n".join(p for p in parts if p)


def _render_inline(el: ET.Element) -> str:
    """Recursively flatten inline content to plain text, preserving **bold** + *italic*."""
    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        tag = child.tag.split("}", 1)[-1]  # strip {namespace}
        inner = _render_inline(child)
        if tag in ("bold",):
            parts.append(f"**{inner}**")
        elif tag in ("italic",):
            parts.append(f"*{inner}*")
        elif tag == "xref":
            parts.append(f"[{inner}]")
        else:
            parts.append(inner)
        if child.tail:
            parts.append(child.tail)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def parse_pub_date(rec: dict) -> str | None:
    """ISO YYYY-MM-DD from esummary PubDate / EPubDate."""
    for key in ("epub_date", "pub_date_raw"):
        v = (rec.get(key) or "").strip()
        if not v:
            continue
        # Common forms: "2024 Jan 15", "2024 Jan", "2024", "2024 Jan-Feb"
        for fmt in ("%Y %b %d", "%Y %b", "%Y-%m-%d", "%Y/%m/%d", "%Y"):
            try:
                d = dt.datetime.strptime(v.split("-")[0].strip()[:11], fmt)
                if fmt == "%Y":
                    return f"{d.year:04d}-01-01"
                if fmt == "%Y %b":
                    return d.replace(day=1).date().isoformat()
                return d.date().isoformat()
            except Exception:
                continue
    return None


def make_citation_key(rec: dict) -> str:
    """Deterministic slug: {Lastname}{YYYY}_{JournalAbbrev}_{PMID}."""
    pmid = rec.get("pmid", "unknown")
    authors = rec.get("authors") or []
    first = (authors[0] if authors else "").split()
    last = first[0] if first else "Anon"
    last = re.sub(r"[^A-Za-z]", "", last) or "Anon"
    pub = parse_pub_date(rec) or "0000-00-00"
    year = pub[:4]
    journal = rec.get("journal", "Journal")
    jabbr = re.sub(r"[^A-Za-z0-9]", "", journal)[:20] or "J"
    return f"{last}{year}_{jabbr}_{pmid}"


def write_article(outdir: Path, rec: dict, jats_xml: str | None,
                  with_images: bool, throttle: RateLimiter) -> dict:
    citation_key = make_citation_key(rec)
    article_dir = outdir / citation_key
    article_dir.mkdir(parents=True, exist_ok=True)

    pmc_id = rec.get("pmc_id")
    image_refs = extract_image_refs(jats_xml or "", pmc_id) if pmc_id else []
    images_dir = article_dir / "images"
    images_meta: list[dict] = []
    if with_images and image_refs:
        for ref in image_refs:
            href = ref["href"]
            # Local filename — preserve href if it has extension, else add .jpg
            fname = href if "." in href else href + ".jpg"
            fname = re.sub(r"[^A-Za-z0-9._-]", "_", fname)
            local = images_dir / fname
            ok = fetch_image(ref["url"], local, throttle)
            images_meta.append({
                "href": href, "url": ref["url"], "kind": ref["kind"],
                "caption": ref.get("caption"),
                "local_path": str(local) if ok else None,
                "local_filename": fname if ok else None,
                "fetched": ok,
            })
    elif image_refs:
        # captured URLs but didn't download (cm1 binary-free path)
        for ref in image_refs:
            images_meta.append({
                "href": ref["href"], "url": ref["url"], "kind": ref["kind"],
                "caption": ref.get("caption"),
                "local_path": None, "local_filename": None,
                "fetched": False,
            })

    md_lines = []
    if jats_xml:
        md_lines.append(jats_to_markdown(jats_xml))
    if not md_lines or not md_lines[0].strip():
        md_lines = [
            f"# {rec.get('title', 'Untitled')}",
            "",
            f"_{rec.get('journal', '')}, {parse_pub_date(rec) or 'date unknown'}_",
            "",
            "## Abstract\n\n_(JATS XML not retrieved.)_",
        ]
    # Append fetched-image gallery so raw.md is reader-complete
    if with_images and any(im["fetched"] for im in images_meta):
        md_lines.append("\n\n## Figures\n")
        for im in images_meta:
            if not im["fetched"]:
                continue
            cap = im.get("caption") or im["href"]
            md_lines.append(f"![{cap}](images/{im['local_filename']})\n\n_{cap}_")
    raw_md = "\n".join(md_lines)
    (article_dir / "raw.md").write_text(raw_md, encoding="utf-8")

    manifest = {
        "citation_key": citation_key,
        "pmid": rec.get("pmid"),
        "doi": rec.get("doi"),
        "pmc_id": pmc_id,
        "title": rec.get("title"),
        "journal": rec.get("journal"),
        "publish_date": parse_pub_date(rec),
        "authors": rec.get("authors") or [],
        "pub_types": rec.get("pub_types") or [],
        "oa_status": "positive" if pmc_id else "unknown",
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source_pipeline": "pubmed_oa_hd_reviews",
        "source_query_label": "hemodialysis_oa_review",
        "raw_md_path": str((article_dir / "raw.md").resolve()),
        "raw_md_bytes": len(raw_md.encode("utf-8")),
        "has_full_text": bool(jats_xml and len(raw_md) > 1000),
        "images": images_meta,
        "images_fetched": sum(1 for i in images_meta if i["fetched"]),
        "images_total": len(images_meta),
    }
    (article_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    p = argparse.ArgumentParser()
    today = dt.date.today()
    p.add_argument("--since", default=(today - dt.timedelta(days=365)).isoformat(),
                   help="ISO date YYYY-MM-DD (default: today - 365d)")
    p.add_argument("--until", default=today.isoformat())
    p.add_argument("--out", type=Path, default=None,
                   help="Output dir (one folder per article + index.jsonl). "
                        "Required unless --dry-run.")
    p.add_argument("--limit", type=int, default=0,
                   help="Cap fetch count (0 = no cap, fetch all matches).")
    p.add_argument("--pmid", action="append", default=None,
                   help="Single-PMID test mode; bypass esearch. Repeatable.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print esearch count + sample PMIDs; do not fetch JATS.")
    p.add_argument("--with-images", action="store_true",
                   help="Download <fig>/<table-wrap>/<inline-graphic> binaries to "
                        "<out>/<key>/images/. Only run on a binary-capable host "
                        "(per LAW: hm4 / mbp / hm4-ssd; NOT cm1 / mba ~/repos/*).")
    args = p.parse_args()

    throttle = RateLimiter(per_second=8.0 if API_KEY else 2.5)

    if args.pmid:
        # test mode: skip esearch
        pmids = list(args.pmid)
        total = len(pmids)
    else:
        query = QUERY_TEMPLATE.format(
            since=args.since.replace("-", "/"),
            until=args.until.replace("-", "/"),
        )
        print(f"[esearch] query: {query}", file=sys.stderr)
        retmax = args.limit if args.limit > 0 else 10000
        total, pmids = esearch(query, retmax=retmax, throttle=throttle)
        print(f"[esearch] {total} matches; PMIDs returned: {len(pmids)}", file=sys.stderr)

    if args.dry_run:
        for pid in pmids[:10]:
            print(f"  PMID: {pid}", file=sys.stderr)
        return 0

    if not args.out:
        print("--out required (or use --dry-run)", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    if args.limit > 0:
        pmids = pmids[: args.limit]

    print(f"[fetch] processing {len(pmids)} PMIDs → {args.out}", file=sys.stderr)
    index_path = args.out / "index.jsonl"
    with index_path.open("w", encoding="utf-8") as idxf:
        # batch esummary by 50 to reduce roundtrips
        for batch_start in range(0, len(pmids), 50):
            batch = pmids[batch_start: batch_start + 50]
            try:
                summaries = esummary(batch, throttle)
            except Exception as e:
                print(f"  esummary batch {batch_start}: {e}", file=sys.stderr)
                continue
            for rec in summaries:
                pmc_id = rec.get("pmc_id")
                xml = efetch_pmc_xml(pmc_id, throttle) if pmc_id else None
                manifest = write_article(args.out, rec, xml, args.with_images, throttle)
                idxf.write(json.dumps(manifest, ensure_ascii=False) + "\n")
                print(f"  ✓ {manifest['citation_key']}  full_text={manifest['has_full_text']}"
                      f"  imgs={manifest['images_fetched']}/{manifest['images_total']}",
                      file=sys.stderr)

    print(f"[done] {len(pmids)} articles → {args.out}; index at {index_path}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
