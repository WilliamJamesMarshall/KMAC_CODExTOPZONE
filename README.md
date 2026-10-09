# OSS AX Task matching logic

The 2026 AI voucher supplier pool ingestion and Supabase schema are documented
in [docs/supplier-knowledge-base.md](docs/supplier-knowledge-base.md).
The v0.3 AX Task candidate import and its limits are documented in
[docs/ax-matching.md](docs/ax-matching.md).

## Local environment

Fill the blank fields in `.env` at the repository root. `env.example` documents
the required fields and is safe to commit; `.env` is ignored by Git. The local web
server reads `OSS_WORKBOOK_PATH`. The OpenAI AX extraction command and local
Business Model / AX opportunity analysis read
`OPENAI_API_KEY` and optionally `OPENAI_MODEL` (default `gpt-6-luna`). Both
entry points load `.env` automatically without overriding process environment
variables. Other batch commands still take an explicit `--workbook` path.
The local server reads `SUPABASE_URL` and `SUPABASE_SECRET_KEY` to add source
details to recommended supplier cards. The secret key stays on the server.

The matching logic reads the supplied v0.3 Excel workbook in memory, keeps
workbook review states,
maps website evidence to AX Task candidates, and retrieves
provisional supplier candidates through common Task IDs.

## What is implemented

- Workbook audit for all 12 sheets, duplicate IDs, review states, out-of-scope
  links, and possible duplicate supplier identities.
- In-memory Task, Supplier, Solution, detailed-link, and scan-evidence models.
- Candidate retrieval by Task ID. Scan candidates and detailed coding remain
  separate from verified homepage capabilities.
- Bounded public-site crawl and a conservative website-text baseline for the
  first pilot tasks: N009, J014, J015, J016, J020, and J021.
- A task-fit-only provisional ranking with source quotations and review labels.
- Project-like quotations are surfaced for review; a structured project proposal
  requires an explicit page quote. Projects are never inferred from a general
  solution description.

The workbook parser is in-memory; the separate supplier ingestion pipeline has
created a Supabase knowledge-base schema and imported the 2026 supplier pool
and bounded homepage crawl. See the linked supplier documentation for counts
and current gaps. Workbook `미검토` rows are not confirmed capability. The
crawler does not infer projects, clients, outcomes, dates, deployment fit, or
budgets.

## Run

Install Python 3.11+ and the pinned dependency, then from this repository:

```powershell
python -m pip install -e .
oss --workbook "PATH_TO_V0.3.xlsx" audit
oss --workbook "PATH_TO_V0.3.xlsx" candidates --task J014 --exclude-scan
oss --workbook "PATH_TO_V0.3.xlsx" analyze --demand-pages demand-pages.json
```

## Local front screen

The front screen is a local web app. It uses the workbook for Task matching
and reads 2026 AI voucher supplier details from Supabase on the server:

On Windows, double-click `dev.cmd` in the project root. It locates the supplied
v0.3 workbook in OneDrive, starts the local server if needed, waits until it is
ready, and opens the site in the default browser. If the workbook has moved,
set `OSS_WORKBOOK_PATH` to its absolute path before running the file.
Install the web analysis dependency with `python -m pip install -e ".[ax-llm]"`.

```powershell
oss-web --workbook "PATH_TO_V0.3.xlsx"
```

Open `http://127.0.0.1:8765`. Enter a public demand-company homepage URL, or
choose **예시 결과 보기** to inspect the layout using a fictional demand company.
The Business Model field crawls company, product, R&D and production pages,
extracts exact-quote facts, groups the core business and supported activities,
then writes only **가치 제안** and **핵심 활동**. A separate model pass checks the
two fields against their citations; unsupported claims are revised or left
unknown. Each displayed field exposes its source quotes. This path requires an
OpenAI API key in `.env` and does not write to Supabase.

The AX field uses the verified business functions and value chain to propose
active v0.3 Task IDs. It then checks business relevance, required inputs,
AI mechanism, possible process change, expected effects, KPIs, missing internal
data and human-review safeguards. An independent audit removes unsupported
proposals. The field shows at most two conditional opportunities; only their
Task IDs reach supplier matching. The right field shows at most three
distinct-name supplier candidates from detailed workbook links. Homepage
analysis does not establish data availability or numeric improvements. A
source-linked pool record adds each supplier's specialization, AI solution
description, address, phone number, and representative. If the workbook and
pool identities cannot be corroborated, the card shows an explicit review
status instead of another company's details.

`demand-pages.json` is a UTF-8 array of page extracts:

```json
[
  {
    "url": "https://example.com/quality",
    "title": "품질 관리",
    "text": "당사는 자동차 부품을 생산하며 제품 품질검사를 수행합니다."
  }
]
```

Use `--demand-url https://...` to crawl a public site, or add `--supplier-id`
and `--supplier-pages`/`--supplier-url` to examine one known supplier homepage.
`--output result.json` writes UTF-8 JSON. The page-text baseline intentionally
abstains for wording it does not recognize; an LLM extractor can later submit
proposed Task IDs and exact quotations through `validate_task_evidence`.

The source contract test runs when `OSS_WORKBOOK_PATH` points to the workbook:

```powershell
$env:OSS_WORKBOOK_PATH = "PATH_TO_V0.3.xlsx"
python -m unittest discover -s tests -v
```

## Current data limits

The 274 workbook activity links include three references to J005/J007, which
are absent from the active 147-task list and marked for purpose clarification
in the workbook. The audit retains them; candidate lookup excludes them.
Company IDs from detailed coding and AI scan can refer to the same name, so
ranked results expose possible same-name IDs and an identity-review flag. Their
evidence and scores stay separate until the identities are checked.

The first matching score uses only Task fit. Other factors in the OSS plan need
separately collected and verified project, industry, deployment, budget, and
support data before they can affect ranking.
