# 2026-05-04 — Consolidate all auto crawlers into tw-medical-scrapers

## Directive

Copper directive 2026-05-04: 整合所有 auto crawlers 到 tw-medical-scrapers/ 單一 repo, 包含 GitHub 上散落的副本一併拉下來 merge, 不要多頭馬車。

This accelerates the existing Roadmap active sprint in `_admin-private/CLAUDE.md`:
> Migrate scrapers to public `tw-medical-scrapers` repo — extract NHI/TFDA/MOHW scrapers from `_admin-private/.script/` and `boan-emr/scripts/` into the new public repo with PEP 723 standalone style; first scraper landed 2026-04-30 (NHI drug formulary), rest TODO. (2-4 weeks active sprint)

## Source repo audit (4 sources)

| Source | Path | Repo state | Scope |
|---|---|---|---|
| **B1 dest (canonical)** | `tw-medical-scrapers/scrapers/` | public, MIT, 2026-04-30 init | 2 scrapers already standalone |
| **B2 cm1 local** | `_admin-private/.script/` | private, post-Phase-9c | 12 NHI/TFDA scrapers + 1 dispatch helper |
| **B3 cm1 local** | `boan-emr/scripts/` | BoAn-private | 6 scrapers (partial dup of B2) |
| **B4 GitHub stale** | `copper0722/vault-scripts` (cloned to `/tmp/scraper-merge-staging/vault-scripts/` for audit) | public, last commit 2026-04-22 (pre-Phase-9c) | 12 scraper near-dup of B2 with whitespace/EOL differences only |

## Companion private repo: `personal-scrapers`

Per Copper directive 2026-05-04 plan (b), private/login-required scrapers split
into a separate private repo `copper0722/personal-scrapers` (created
2026-05-04). Scope: Garmin Connect, TSN exam (society login), Zotero, etc. —
anything that needs personal credentials and cannot be public.

`tw-medical-scrapers/` (this repo) hosts public anonymous-access TW gov-medical
data only. Subscription-protected medical journal downloaders (NEJM, Nature)
remain as standalone Chrome-extension repos under `dev/`
(`dev/journal-downloader/`, `dev/download-nejm-video/`).

GitHub repos audited but **no net-new scrapers found**:
- `copper0722/vault` — broken/empty repo, ignore
- `copper0722/clinic-ehr` — pre-Phase-9c clinic EMR, no NHI/TFDA scrapers (only 3 false-positive hits in dialysis WebApp)
- `copper0722/personal-assistant` — old Aiko home, retired 2026-04-17, no scrapers
- `copper0722/governance` — empty placeholder, no scrapers

## Standalone conformance criteria (from `tw-medical-scrapers/AGENTS.md`)

1. **One file = one scraper**, no `from utils import …` from sibling
2. **PEP 723 inline metadata** (`# /// script` block at top with deps)
3. **No DB writes**, no hidden state, output to `--out` flag
4. **Idempotent re-run** (skip already-downloaded; `--force` to override)
5. **Cloudflare-aware** (use `cloudscraper`, not bare `requests`)
6. **Public-access only** (no POST/login/cookie persistence)
7. **Clean filenames** (sanitized)

## Per-scraper migration plan

### Already done (B1, no action)

| target name | status |
|---|---|
| `nhi_drug_formulary_download.py` | ✅ standalone (2026-04-30) |
| `tfda_drug_download.py` | ✅ standalone (2026-04-30) |

### Migrate-asis (low cost, mostly ready)

| source path | target name | gap to close | rename |
|---|---|---|---|

(none — all need at least PEP 723 + DB write removal)

### Migrate-rewrite (medium cost, structure clear)

Each: add PEP 723 metadata + remove DB writes (replace with `--out` JSONL/CSV) + add argparse + add `--force`/`--skip-existing` + verify cloudscraper usage. Estimated 30–90 min per scraper on hm4.

| source path | target name | rewrite work | source URL/host |
|---|---|---|---|
| `_admin-private/.script/tfda-sitelist-scraper.py` | `tfda_sitelist_scraper.py` | strip events.db, add --out JSONL, add PEP 723 | fda.gov.tw siteList (藥品/醫材安全) |
| `_admin-private/.script/tfda-news-scraper.py` | `tfda_news_scraper.py` | strip events.db, add --out, PEP 723 | fda.gov.tw 公告/新聞/預告法規 |
| `_admin-private/.script/nhi-meeting-scraper.py` | `nhi_meeting_scraper.py` | strip events.db, --out, PEP 723, ROC date helper inline | nhi.gov.tw lp-3379 / lp-3380 |
| `_admin-private/.script/nhi-payment-monitor.py` | `nhi_payment_monitor.py` | strip events.db state → --state JSON, --out, PEP 723 | nhi.gov.tw lp-3778 (支付標準全文) |
| `_admin-private/.script/nhi-announcement-scraper.py` | `nhi_announcement_scraper.py` | strip events.db, --out, PEP 723, ROC→ISO date | nhi.gov.tw lp-3257-1 (健保公告) |
| `_admin-private/.script/nhi-regulation-scraper.py` | `nhi_regulation_scraper.py` | strip events.db, --out, PEP 723, doc-ref# extraction | nhi.gov.tw lp-3258-1 (法規公告) |

### Migrate-merge (high cost, overlap consolidation)

| group | members | proposed merge target | rationale |
|---|---|---|---|
| **NHI drug formulary chain** | `_admin-private/.script/nhi-drug-monitor.py` (428L) + `nhi-drug-parser.py` (272L) + `boan-emr/scripts/nhi-drug-formulary-download.py` (158L, untracked) + B1 `nhi_drug_formulary_download.py` (177L, already standalone) | Keep B1 `nhi_drug_formulary_download.py` as the **download-only standalone**. Spin off **`nhi_drug_formulary_parse.py`** as a separate standalone parser that reads .B5 fixed-width Big5 → emits structured CSV/JSONL via `--out`. The monthly-monitor logic (check 25th, detect new release) goes into a third lightweight wrapper `nhi_drug_formulary_monitor.py` that calls the download script and emits state JSON to `--state`. | Single-purpose split; no cross-script imports; each runnable solo. |
| **NHI page/dialysis watch chain** | `_admin-private/.script/nhi-dialysis-monitor.py` (137L) + `_admin-private/.script/nhi-page-monitor.py` (252L, **AppleScript-only**) + `boan-emr/scripts/page-monitor.py` (228L) | Drop `nhi-page-monitor.py` (Safari AppleScript-based, not a standalone-fit Python scraper — keep in `_admin-private/.script/` as a Mac-local change-detector or migrate to `crawler` SKILL only). Merge dialysis-monitor + boan-emr/page-monitor into **`nhi_page_watcher.py`** standalone Python (cloudscraper) with `--urls` flag for arbitrary NHI lp-XXXX URL list, `--state` JSON for hash comparison, `--out` for new-content JSONL. | Multi-URL watcher in one standalone file. AppleScript path stays out of public repo. |
| **NHI regulation RSS+page chain** | `_admin-private/.script/nhi-regulation-scraper.py` (already in migrate-rewrite above) + `boan-emr/scripts/nhi-rss.py` (176L) + `boan-emr/scripts/nhi-regulation-rss.py` (159L) | Keep `nhi_regulation_scraper.py` (page-based scrape per migrate-rewrite list). Add **`nhi_regulation_rss.py`** as separate standalone RSS poller (`--feed lp-3258-1` etc., `--out` JSONL). Merge `boan-emr/scripts/nhi-rss.py` + `nhi-regulation-rss.py` into one. | RSS path is a separate fast lane (3x daily) vs scrape (slower full pull). Two parallel standalones serve different cadence needs. |
| **NHI generic scraper merge** | `boan-emr/scripts/nhi-scraper.py` (647L, lp-3257/3258 → gov_docs.db 3NF) | Subsume into `nhi_announcement_scraper.py` + `nhi_regulation_scraper.py` (above). The 3NF DB write logic is workflow concern, drops out of scraper. | DB write goes away under standalone rule #3. |

### Migrate-rewrite (high cost, complex structure)

| source path | target name | rewrite work |
|---|---|---|
| `_admin-private/.script/nhi-drug-enrichment.py` (559L) | `nhi_drug_enrichment.py` | Heavy: merges NHI CSV + TFDA JSON + PDF rules → DB. Extract pure ingest+merge logic into standalone that reads `--inputs` and writes `--out` JSONL. The `nhi_drug_formulary.db` schema/build logic exits to a separate workflow script outside this repo. |
| `_admin-private/.script/build-clinic-drugs.py` (552L) | `build_clinic_drugs.py` | Heavy: depends on local Access DB + Prospect + NHI + TFDA + WHO ATC merge. **Open question**: keep in tw-medical-scrapers? It's not strictly a public-data scraper since Access DB is private. **Recommendation: leave in `_admin-private/.script/` as workflow orchestrator that calls the standalone scrapers in this repo.** |

### Retire (no migration)

| source path | reason |
|---|---|
| `_admin-private/.script/nhi-page-monitor.py` (252L) | Safari AppleScript-based, conceptually belongs to `crawler` SKILL Pattern 6 (page change monitor); not a Python standalone scraper. Keep in `_admin-private/.script/` for Mac-local change detection only. |
| `boan-emr/scripts/build-clinic-drugs.py` (538L) | Exact-classified dup of `_admin-private/.script/build-clinic-drugs.py`. Already redundant. → archive to `boan-emr/_archive/scripts-retired-2026-05-04-tw-medical-scrapers-merge/`. |
| `boan-emr/scripts/nhi-drug-formulary-download.py` (158L, untracked) | Superseded by B1 standalone (177L). Untracked in git, never committed. → mv to `boan-emr/_archive/scripts-retired-2026-05-04-tw-medical-scrapers-merge/`. |
| `B4 vault-scripts/` (12 NHI/TFDA scrapers, GitHub) | Stale near-dup of B2 with whitespace-only differences. Pre-Phase-9c artifact. → after B2 fully migrated, mark `copper0722/vault-scripts` as **archived** on GitHub via `gh repo edit copper0722/vault-scripts --archive`. |
| `_admin-private/.script/nhi-meeting-extract.py` | Not a web scraper — uses pdfminer.six to extract text from already-downloaded NHI dialysis meeting PDFs. Belongs to a future `tw-medical-policy-archive/workflow/` repo (raw → structured pipeline), not the scraper repo. |

## Final scraper inventory in `tw-medical-scrapers/scrapers/`

After full consolidation:

| # | scraper | purpose | source URL |
|---|---|---|---|
| 1 | `nhi_drug_formulary_download.py` | NHI 健保用藥品項月查詢檔 download | nhi.gov.tw lp-2466-1 |
| 2 | `nhi_drug_formulary_parse.py` *(new)* | Parse Big5 fixed-width .B5 → JSONL | (stdin / --in file) |
| 3 | `nhi_drug_formulary_monitor.py` *(new)* | Monthly check for new release + state JSON | wraps #1, --state |
| 4 | `nhi_drug_enrichment.py` *(rewrite)* | Merge NHI + TFDA + PDF rules | multi-source |
| 5 | `nhi_announcement_scraper.py` *(rewrite)* | NHI 健保公告 | nhi.gov.tw lp-3257-1 |
| 6 | `nhi_regulation_scraper.py` *(rewrite)* | NHI 法規公告 | nhi.gov.tw lp-3258-1 |
| 7 | `nhi_regulation_rss.py` *(new)* | NHI 法規公告 RSS poller | nhi.gov.tw rss-3258-1 |
| 8 | `nhi_meeting_scraper.py` *(rewrite)* | NHI 門診透析會議 / 醫院總額 | nhi.gov.tw lp-3379 / lp-3380 |
| 9 | `nhi_payment_monitor.py` *(rewrite)* | NHI 支付標準全文 versioning | nhi.gov.tw lp-3778 |
| 10 | `nhi_page_watcher.py` *(merged)* | Generic NHI page watcher (--urls) | any nhi.gov.tw lp-XXXX |
| 11 | `tfda_drug_download.py` ✅ | TFDA permits + ingredients open data | data.fda.gov.tw |
| 12 | `tfda_sitelist_scraper.py` *(rewrite)* | TFDA 藥品/醫材安全資訊 | fda.gov.tw siteList |
| 13 | `tfda_news_scraper.py` *(rewrite)* | TFDA 公告/新聞/預告法規 | fda.gov.tw |

13 standalone scrapers covering NHI + TFDA. MOHW + HPA + CDC + city-health + society scrapers TBD (separate sprint after this consolidation).

## Retirement / archive plan

After each new standalone scraper lands and is verified working:

1. **B2 originals** in `_admin-private/.script/`:
   - mv `nhi-{drug-monitor,drug-parser,drug-enrichment,announcement-scraper,regulation-scraper,meeting-scraper,payment-monitor,dialysis-monitor}.py` → `_admin-private/.script/_retired-2026-05-04-tw-medical-scrapers-merge/`
   - mv `tfda-{sitelist-scraper,news-scraper}.py` → same archive
   - keep `nhi-page-monitor.py` (AppleScript-based, not migrated)
   - keep `nhi-meeting-extract.py` (PDF post-processor, not scraper)
   - keep `build-clinic-drugs.py` (workflow orchestrator, will call new standalone scrapers via subprocess)

2. **B3 originals** in `boan-emr/scripts/`:
   - mv `nhi-scraper.py`, `nhi-rss.py`, `nhi-regulation-rss.py`, `page-monitor.py` → `boan-emr/_archive/scripts-retired-2026-05-04-tw-medical-scrapers-merge/`
   - mv `build-clinic-drugs.py` (exact dup) → same archive
   - mv `nhi-drug-formulary-download.py` (untracked superseded) → same archive (or `git rm`)

3. **B4 vault-scripts repo on GitHub**:
   - Add `DEPRECATED.md` to repo root pointing to tw-medical-scrapers
   - Run `gh repo edit copper0722/vault-scripts --archive` to lock the repo as read-only on GitHub

4. **Update cross-references**:
   - `_admin-rules/skills/crawler/SKILL.md` § "Existing Scripts" — update paths from `nhi-X-scraper.py` to `tw-medical-scrapers/scrapers/nhi_X_scraper.py`
   - `_admin-private/CLAUDE.md` Roadmap — mark sprint progress
   - `tw-medical-scrapers/AGENTS.md` § Status — log this consolidation event

## Execution checklist (target: hm4 with cloudscraper test env)

cm1 cannot run cloudscraper to test rewrites; defer rewrite-and-test to hm4. cm1's deliverables in this session:

- [x] Audit + dedup matrix (this doc)
- [x] Spec for each migration class (above tables)
- [ ] Retire 2 known exact-dup files in boan-emr/scripts/ (this session)
- [ ] Update `_admin-private/CLAUDE.md` Roadmap progress (this session)
- [ ] Open task tracker entry (#3 task already opened)

hm4 deliverables (next session):

- [ ] For each scraper in migrate-rewrite list: standalone-ize per AGENTS.md criteria, test with `uv run`, commit to tw-medical-scrapers
- [ ] For migrate-merge groups: design per-group, write merged standalone(s), test, commit
- [ ] Verify each new scraper produces consistent JSONL/CSV output vs old DB-write behavior
- [ ] After all 11 new scrapers land: archive B2 / B3 / B4 originals
- [ ] Update crawler SKILL.md + AGENTS.md + Roadmap

## Audit trail

PG `audit_findings` row: this consolidation has no separate finding (it's an active sprint, not a drift bug). Once complete, mark Roadmap entry done.

Related tasks:
- task #2 — BoAn 學術/ academic PDF migration (separate concern, not blocking this)
- task #3 — this consolidation (parent)
