# AX Task candidate matching, v0.3

The source workbook is
`AX_AI바우처_5범주_600개기업_과업분류_v0.3.xlsx`, SHA-256
`5A501EABC9D6D61F1F429172342F248BE04B9438A50CF93570A6AA6E175A1CF9`.
Its contents are treated as data, not instructions. This work covers AX Task
matching only; it does not create or structure project portfolios.

## Imported evidence

| Source | Evidence rows | Suppliers | Distinct supplier-task pairs | Treatment |
| --- | ---: | ---: | ---: | --- |
| 600-company AI scan | 2,566 | 552 | 1,849 | Candidate, strength 1 |
| Detailed workbook links with exact AI-pool quotation | 105 | 68 | 101 | Candidate, strength 2 |
| High-threshold text classifier on 828 unscanned suppliers | 198 | 156 | 198 | Candidate, strength 1 |

The union is 2,869 task evidence rows, 2,076 distinct supplier-task pairs,
718 suppliers, and 141 of 147 Tasks. All 147 Task definitions are loaded and
retain `unreviewed` status. The remaining 710 suppliers have no Task candidate
meeting these evidence rules. They are not labeled incapable. They have 710
pending `ax_task_review` jobs in `processing_jobs`; these are a review queue,
and no worker runs them automatically.

The 600 workbook scan identities were matched to current AI voucher records by
normalized company name and exact solution text for 598 rows. Two names were
unique but the current description had changed; all 2,566 scan quotations
still appear in the current pool text after whitespace normalization. For
detailed workbook links, 125 quotations absent from the current AI pool, 41
unresolved identities, and three inactive Task IDs were excluded. AX voucher
and AI voucher are distinct source programs, so a shared name alone does not
establish that an AX quotation belongs to the AI pool row.

The text classifier is trained only on the 600 unreviewed scan labels and
current pool descriptions. At score threshold 0.65, five-fold held-out micro
precision against those labels was 0.9052 (116 predictions). This measures
agreement with the workbook's provisional labels, not verified capability or
real-world accuracy; the threshold was selected after inspecting these folds,
so the estimate may be optimistic. Only 198 candidates across 156 of the other 828 companies
passed the threshold. Each candidate stores an exact excerpt from the pool
description; its `confidence` is an uncalibrated model score. No low-score
prediction is inserted.

The same classifier was tested on held-out supplier website text for 327 of
the scanned companies with readable pages. At threshold 0.65, agreement with
the provisional scan labels fell to 0.394 micro precision (33 predictions).
Website text therefore did not generate additional automatic Task links.
The crawled pages remain available for quotation-based review.

All imported Task evidence has `verification_status = 'candidate'`. The
`supplier_task_profiles` serving table remains empty until Task links are
reviewed and a scoring rule is approved. A candidate lookup can use:

```sql
select s.canonical_name, e.task_id, t.task_name,
       e.mapping_method, e.evidence_strength, e.confidence, e.evidence_text
from public.capability_evidence e
join public.suppliers s on s.id = e.supplier_id
join public.ax_tasks t on t.task_id = e.task_id
where e.task_id = 'J014'
order by e.evidence_strength desc, e.confidence desc nulls last;
```

The unmatched review queue is visible with:

```sql
select s.canonical_name, p.sply_pool_no, p.specialization, p.ai_solution_text
from public.processing_jobs j
join public.suppliers s on s.id = j.supplier_id
join public.pool_entries p on p.supplier_id = s.id
where j.job_type = 'ax_task_review' and j.status = 'pending'
order by p.sply_pool_no;
```

## Repeatable import

```powershell
python -m oss.ax_import --workbook "PATH_TO_V0.3.xlsx" --prepared data/pool/2026/prepared.json --output-dir data/ax/v03/import-sql
python -m pip install -e ".[ax-inference]"
python -m oss.ax_predict --workbook "PATH_TO_V0.3.xlsx" --prepared data/pool/2026/prepared.json --output-dir data/ax/v03/predicted-sql
```

Apply `tasks.sql`, then the numbered `evidence-*.sql` batches, then the
numbered `predicted-*.sql` batches through a privileged connection. The
generated IDs make each batch safe to rerun. The raw workbook and generated
SQL are local and excluded from Git. Run
[`queue_unmatched_ax_review.sql`](../sql/queue_unmatched_ax_review.sql) to
record suppliers that still need review.

## Prepared OpenAI API pass for the 710 review jobs

No API request has been sent: `OPENAI_API_KEY` is not set in this execution
environment, and the user requested code preparation only. The extractor uses
the [Responses API structured output format](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)
with the `gpt-6-luna` model by default, following its
[model documentation](https://developers.openai.com/api/docs/models/gpt-6-luna).
It sends the 147 Task definitions, the supplier's pool description, and at
most three selected public website page excerpts. It never sends local contact
details or the workbook file. The model may return up to five Task candidates
or an empty list.

Before saving a result, the code checks every Task ID, source ID, and exact
quotation against the text actually supplied. Results are local JSON files
with model usage and source hashes. The separate SQL builder rechecks the
source hashes and quotes, then writes idempotent `capability_evidence` inserts
with `candidate` status. It never creates project or portfolio records.

```powershell
python -m pip install -e ".[ax-llm]"
python -m oss.ax_llm --workbook "PATH_TO_V0.3.xlsx" --prepared data/pool/2026/prepared.json --matched-ids data/ax/v03/import-sql/matched-pool-ids.json --matched-ids data/ax/v03/predicted-sql/matched-pool-ids.json --crawl-dir data/pilot/2026 --output-dir data/ax/v03/llm-results --limit 10 --dry-run
```

After setting `OPENAI_API_KEY` in the ignored root `.env` or the local process environment, run the same
command without `--dry-run` for a 10-company pilot. Inspect the saved JSON
before increasing `--limit` to 710. Completed company files are skipped on
rerun. Generate SQL only after review:

```powershell
python -m oss.ax_llm_import --workbook "PATH_TO_V0.3.xlsx" --prepared data/pool/2026/prepared.json --crawl-dir data/pilot/2026 --results-dir data/ax/v03/llm-results --output-dir data/ax/v03/llm-sql
```

The model's semantic judgment can still be wrong even when its quote is exact.
The SQL output requires a review gate before application. The 710 review jobs
remain pending until that gate is complete; this preparation does not run them.
