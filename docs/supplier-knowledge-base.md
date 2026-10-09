# AI voucher supplier knowledge base

The 2026 AI voucher pool is the source of supplier master records. The public
listing returned 1,428 rows on 143 pages on 2026-10-09. `splyPoolNo` is kept as
a source ID. Internal relationships use UUIDs. Company names are display values,
not matching keys.

## Reproduce the source snapshot

```powershell
python -m oss.pool_snapshot --year 2026 --output-dir data/pool/2026
python -m oss.pool_prepare --records data/pool/2026/records.json --output data/pool/2026/prepared.json
python -m oss.pool_import --snapshot-dir data/pool/2026 --output-dir data/pool/2026/import-sql
python -m oss.pool_solutions --snapshot-dir data/pool/2026 --output-dir data/pool/2026/solution-sql
```

`data/` is ignored by Git because pool records include public business contact
details and the crawl output can be large. `manifest.json` holds the source count
and a SHA-256 of the normalized record list. The import SQL is generated from
that snapshot and can be rerun. It does not merge same-name suppliers.

The source website field is preserved verbatim. URL parsing identifies valid
HTTP(S) candidates, adds HTTPS for bare domains, separates multiple addresses,
and rejects emails and a link back to the voucher pool itself. Multiple URLs
remain unclassified until reviewed; none is promoted to the primary homepage.

`pool_solutions` extracts only lines that explicitly label a solution or
product name and include following descriptive text. The source-linked
[`backfill_pool_fallback.sql`](../sql/backfill_pool_fallback.sql) adds one
unnamed candidate for every supplier without a safely separable product name,
using the exact pool `aiSolution` text. These are all `candidate`/`unreviewed`;
the accompanying pool evidence has strength 1. No project, client, outcome, or
AX Task is inferred from broad descriptions.

## Website crawl

```powershell
python -m oss.supplier_pilot --prepared data/pool/2026/prepared.json --output-dir data/pilot/2026 --count 1428 --max-pages 6 --workers 4
python -m oss.crawl_import --crawl-dir data/pilot/2026 --output-dir data/pilot/2026/import-sql --year 2026 --batch-size 10
```

The crawler reads `robots.txt`, follows only same-host redirects, limits page
count and response bytes, and stops on HTTP 429. It records distinct statuses
for missing URLs, robots restrictions, failed requests, and pages without
readable text. The latter may be JavaScript-only sites. Raw fetched HTML is
saved locally under `data/pilot/2026/raw/`; its Supabase Storage upload still
requires a server-side Storage credential. `web_pages.storage_path` stays null
until an upload succeeds. `crawl_import` outputs idempotent SQL batches for
`crawl_runs`, `web_pages`, and `page_chunks`; apply them with a privileged
database connection in batch-number order.

## 2026-10-09 import audit

| Item | Count |
| --- | ---: |
| Suppliers and pool rows | 1,428 each |
| Supplier-domain candidates | 1,342 (1,335 suppliers) |
| Latest crawl: readable pages | 764 suppliers |
| Latest crawl: no readable pages | 213 suppliers |
| Latest crawl: failed request | 336 suppliers |
| Latest crawl: robots disallowed | 15 suppliers |
| Latest crawl: rate limited | 7 suppliers |
| Latest crawl: no usable URL | 93 suppliers |
| Latest crawl: unique stored pages | 2,388 |
| Latest crawl: text chunks | 4,908 |
| Source-linked solution candidates | 1,490 (197 named, 1,293 unnamed) |
| Pool-description evidence records | 1,490 |

The crawler returned 2,389 page records; one repeated URL was deduplicated for
storage. Two suppliers were refreshed after an initial pilot, so the database
also retains their earlier crawl runs (1,430 runs and 2,390 pages in history).
Queries for current coverage should use the latest run per supplier.

The migration files create the supplier, source, crawl, solution, project,
evidence, and task profile tables. All are private by default: RLS is enabled
and browser roles have no table grants. The `supplier-crawl` Storage bucket is
private. Public catalog policies and views should be added only after the
reviewed fields and audience are defined.

## Evidence rules

- A pool `aiSolution` description is a source claim, not a verified homepage
  finding. Keep its source entry and review status.
- Broad specialization labels alone do not establish a specific AX Task.
- A project, client, date, or outcome requires an explicit source passage; use
  `NULL` when the source does not state it.
- The v0.3 workbook's 147 tasks and 600 AI-scan rows are now available and
  imported as described in [AX matching](ax-matching.md). Its scan results stay
  candidates after import.
- `supplier_task_profiles` should be recalculated from reviewed links and
  evidence using a versioned deterministic scoring rule.

The original workbook is now available at the user-provided OneDrive path.
`ax_tasks` and candidate task evidence are populated. Task profiles are still
empty because none of the imported task links have been reviewed or verified.
Website content is stored as pages/chunks. Portfolio structuring is outside
the current request. The private Storage bucket exists, but raw HTML currently
remains only in ignored local `data/`.

## Database checks

```sql
select count(*) from public.suppliers;
select count(*), count(distinct sply_pool_no) from public.pool_entries
where source_program = 'AI바우처' and source_year = 2026;
select count(*) from public.supplier_domains;
select count(*) from public.crawl_runs;
select count(*) from public.web_pages;
select count(*) from public.page_chunks;
```
