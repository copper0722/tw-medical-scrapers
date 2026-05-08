# tw-medical-scrapers — agent card

Public scraper collection for Taiwan government + medical public data
sources. Bootstrapped 2026-04-30. Intended to be public-share-ready
(MIT license).

## Scope

Public-data scrapers only. NHI / TFDA / 衛福部 announcements, drug
formularies, regulations. **No** patient data, **no** login-walled
sources, **no** paywalled content.

**Out of scope (Copper directive 2026-05-08)**:

- **PDF binary crawl + extraction** — belongs to `~/repos/wiki_raw/`
  (raw + binary canonical home), not here. Scrapers in this repo emit
  only structured doc-index metadata (uid, title, publisher, doc_type,
  publish_date, source_url, ref_number); PDF bodies flow through wiki_raw's
  MinerU / pre-note pipeline separately. If a scraper needs to surface a
  PDF *URL* in the gov-docs index, that's fine — it lands in the JSONL
  `files: []` field and ends up in PG `tw_gov_docs.gov_doc_files.url`,
  but the binary fetch + body extraction is wiki_raw's job, not ours.
- **Gmail-attachment ingest** — replaced by the inbox flow. Gov dept
  attachments (NHI / TFDA / MOHW / CDC / 衛生局) arrive in
  `~/Library/Mobile Documents/com~apple~CloudDocs/Downloads/` (manually
  or via Gmail forwarding), and wiki_raw picks them up from there
  per Law §Source ingest entry. No scraper in this repo polls Gmail.
- **Login-required scrapers** — split out to private companion repo
  `personal-scrapers` (Garmin, TSN exam fetcher, etc.).

## File layout

| path | purpose |
|---|---|
| `scrapers/` | one .py per scraper. Each is **standalone**: PEP 723 inline metadata, no shared internal modules. |
| `docs/` | source-specific docs (URL maps, format specs, cadence notes). |
| `README.md` | external-facing introduction (visible to public). |
| `AGENTS.md` | this card (M2M agent guidance). |
| `LICENSE` | MIT. |

## Author rules for new scrapers

1. **One file = one scraper**. No `from utils import …` from a sibling file. Copy-paste friendly.
2. **PEP 723 inline metadata**. Top of file:
   ```python
   # /// script
   # requires-python = ">=3.10"
   # dependencies = ["cloudscraper", "beautifulsoup4"]
   # ///
   ```
   Run with `uv run scrapers/X.py` or classic pip+python3.
3. **No hidden state**. Output to `--out` (user-specified) or default
   `./<scraper-name>/`. No DB writes, no fixed home-dir paths.
4. **Idempotent re-run**. Skip already-downloaded files. Add `--force` if
   override needed.
5. **Cloudflare-aware**. Use `cloudscraper` (not bare `requests`) for any
   cf-mitigated source.
6. **Public-access only**. No POST, no login, no cookie persistence. Read
   the source as an anonymous browser would.
7. **Clean filenames**. NHI returns multi-line `Content-Disposition`
   filenames — sanitize to `{period}_{kind}.{ext}` before saving.

## Cross-refs

- Author's private workflow vault (`copper0722/_admin-private`) holds the
  pre-standalone versions of these scrapers — they live in
  `_admin-private/.script/` and `boan-emr/scripts/`. Migration to here is
  ongoing; private versions should be retired or converted to thin
  wrappers calling this repo.
- Taiwan public-health Law/policy registries imported from these
  scrapers feed into PG schema `tw_gov_docs` and `tw_drug` in the
  author's private vault (`vault_main` on hmj).

## Status

| date | event |
|---|---|
| 2026-04-30 | repo bootstrap; first scraper `nhi_drug_formulary_download.py` |
| 2026-05-08 | gov-docs pipeline (NHI/TFDA announcements + regulations) live end-to-end. 4 scrapers added: `nhi_regulation_rss`, `nhi_listing_scrape`, `tfda_news_rss`, `nhi_page_monitor`. Output JSONL → `_admin-private/.script/import_gov_docs_to_pg.py` → hmj `tw_gov_docs.gov_docs` → `personal-website/scripts/sync-pg-gov-docs-to-data.py` (prebuild) → `https://copper0722.com.tw/gov-docs/`. PDF crawl + Gmail ingest scoped out (see above). |

## TODO

- [x] NHI announcement scraper (lp-3257) — `nhi_listing_scrape.py` ✅ 2026-05-08
- [x] NHI regulation scraper (lp-3258) — `nhi_listing_scrape.py` + `nhi_regulation_rss.py` ✅ 2026-05-08
- [x] NHI payment-standard scraper (np-3708) — `nhi_listing_scrape.py` covers ✅ 2026-05-08
- [x] TFDA news RSS (13 feeds) — `tfda_news_rss.py` ✅ 2026-05-08
- [x] NHI watched static pages (lp-3719/3778/3721/3725/6109 dialysis-meetings) — `nhi_page_monitor.py` ✅ 2026-05-08 (lp-6109 returned 0 attachments — page uses non-anchor structure; follow-up parse needed)
- [ ] **lp-6109 透析會議紀錄** parsing — page structure differs (no inline `<a href ending pdf>`); needs separate parser. Critical for clinic-policy tracking.
- [ ] TFDA permits + ingredients (open data InfoId=36 / 43) — extract from `boan-emr/_data/tw-drugs/build-tw-drugs.py` (drug DB, separate pipeline from gov-docs)
- [ ] 衛福部公告 / mohwlaw — not yet drafted; covers MOHW direct-publish channels not included in NHI / TFDA RSS
- [ ] Schedule the 4 live scrapers as cm1 launchd jobs (Copper directive 2026-05-08「走 cm1」). Cadence: nhi_regulation_rss + tfda_news_rss every 4–6h (RSS is fast); nhi_listing_scrape weekly (paginated HTML, heavier); nhi_page_monitor daily. Register in `vault_main.admin_ops.schedule_registry`.
- [ ] CI: `uv run` smoke test per scraper on each PR
