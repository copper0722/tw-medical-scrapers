# tw-medical-scrapers — agent card

Public scraper collection for Taiwan government + medical public data
sources. Bootstrapped 2026-04-30. Intended to be public-share-ready
(MIT license).

## Scope

Public-data scrapers only. NHI / TFDA / 衛福部 announcements, drug
formularies, regulations. **No** patient data, **no** login-walled
sources, **no** paywalled content.

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

## TODO (extraction roadmap)

- [ ] NHI announcement scraper (lp-3257) — port from `boan-emr/scripts/nhi-scraper.py`
- [ ] NHI regulation scraper (lp-3258) — port from `boan-emr/scripts/nhi-regulation-rss.py`
- [ ] NHI payment-standard scraper (np-3708) — currently unwritten
- [ ] TFDA permits + ingredients (open data InfoId=36 / 43) — extract from `boan-emr/_data/tw-drugs/build-tw-drugs.py`
- [ ] TFDA news RSS (13 feeds) — port from `boan-emr/scripts/tfda-news.py`
- [ ] 衛福部公告 / mohwlaw — not yet drafted
- [ ] CI: `uv run` smoke test per scraper on each PR
