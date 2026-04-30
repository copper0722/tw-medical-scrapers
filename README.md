# tw-medical-scrapers

**Standalone Python scrapers for Taiwan public-domain government + medical
data sources.**

Each scraper is a single self-contained file. No project setup, no
package install dance: drop the file anywhere and run it.

## Why this repo

Taiwan's NHI (健保署) and TFDA (食藥署) publish authoritative drug,
regulation, and policy data on websites guarded by Cloudflare bot
challenges. Reproducing the data locally — for clinical apps, research,
EBM workflows, or simply offline reference — requires bypassing the
challenge and parsing the published format. These scrapers do exactly
that, using `cloudscraper` to clear the JS challenge and idiomatic
Python to parse, structure, and emit clean output.

The scripts ship with **PEP 723 inline metadata** — they declare their
own dependencies inside the file. With [`uv`](https://docs.astral.sh/uv/)
installed, just run:

```bash
uv run scrapers/nhi_drug_formulary_download.py
```

`uv` resolves and caches the deps automatically. No virtualenv to manage,
no `requirements.txt` to commit.

If you don't use `uv`, classic pip works too:

```bash
pip install --user cloudscraper beautifulsoup4
python3 scrapers/nhi_drug_formulary_download.py
```

## Scrapers (current)

| Script | Source | Output | Cadence |
|---|---|---|---|
| `nhi_drug_formulary_download.py` | NHI 健保用藥品項月查詢檔 (lp-2466-1) | 2 ZIPs/period (.B5 + .TXT, ~8 MB each) | monthly, ~25th |

## Scrapers (planned — extracting from author's private workflow)

| Source | Status | Notes |
|---|---|---|
| NHI 健保公告 (lp-3257) | drafted in private repo | needs standalone-ize |
| NHI 法規公告 (lp-3258) | drafted in private repo | needs standalone-ize |
| NHI 支付標準異動 (np-3708) | drafted in private repo | needs standalone-ize |
| NHI 健保藥品給付規定 | not started | scope clarification needed |
| TFDA 藥品許可證 (open data InfoId=36) | drafted | extracting from build-tw-drugs.py |
| TFDA 處方成份 (open data InfoId=43) | drafted | as above |
| TFDA 新聞 (RSS, 13 feeds) | drafted | needs standalone-ize |
| 衛福部公告 / 全民健康保險法函釋 (mohwlaw) | not started | |

## Design rules

1. **Standalone-by-construction** — one file = one scraper. PEP 723 inline
   metadata. No shared internal modules. Copy-paste friendly.
2. **No private state** — output to user-specified path; no hidden cache,
   no implicit DB write. Caller decides what to do with the data.
3. **Read-only HTTP** — never POST to the source website beyond what the
   browser GET does. No login flows. Source must be public-access.
4. **Idempotent re-run** — repeated runs skip already-downloaded files
   (size check or mtime check), unless `--force` is passed.
5. **Clean exit codes** — 0 on success, non-zero on failure. Stderr for
   errors, stdout for progress.
6. **Cloudflare-aware** — use `cloudscraper` (not `requests`) for any
   site behind cf-mitigated challenges. Document if a source needs more
   (e.g. browser automation).
7. **No personal identifiers** — these scrapers fetch public data only;
   never log or store IPs, cookies, session tokens beyond what cloudscraper
   manages internally during a single run.

## Status

Bootstrap commit: 2026-04-30. First scraper landed:
`nhi_drug_formulary_download.py`. Author intends to gradually extract +
standardize the rest of his private scraper collection here.

Scope is "Taiwan medical / public-health public data sources". Out of
scope: anything requiring login, anything proprietary or paywalled,
clinical patient data of any kind.

## License

MIT (see [LICENSE](./LICENSE)).

## Contributing

Standalone-ize a private scraper or add a new public-data source via PR.
Keep the design rules above in mind. One file, PEP 723 metadata, idempotent.

## Author

Built and maintained by Wang Chieh-Li (王介立, Copper) — nephrologist,
hemodialysis specialist, Taipei. Public companion to the author's
private medical/clinical knowledge vault. Critique / PR welcome.
