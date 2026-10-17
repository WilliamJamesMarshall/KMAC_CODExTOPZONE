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

Live service: [OSS AX matching](https://oss-ax-591110969614.asia-northeast3.run.app/).
Deployment and live checks: [verification record](docs/cloud-run-live-verification-2026-10-17.md).

For Cloud Run deployment, use the production `oss-cloud` entrypoint and the
repository `Dockerfile`. Account setup, private Excel delivery, durable limits,
secrets, image checks, and deployment commands are in
[the Cloud Run setup guide](docs/cloud-run-supabase-deployment-guide.md).
The local `oss-web` command below remains for development.

The front screen is a local web app. It uses the workbook for Task matching
and reads 2026 AI voucher supplier details from Supabase on the server:

On Windows, double-click `dev.cmd` in the project root. It locates the supplied
v0.3 workbook in OneDrive, starts the local server if needed, waits until it is
ready, and opens the site in the default browser. The launcher checks the running
server's project and source revision and restarts its own outdated instance.
Screen files are served without browser caching, and the opened URL includes
the current revision. If the workbook has moved,
set `OSS_WORKBOOK_PATH` to its absolute path before running the file.
Install the web analysis dependency with `python -m pip install -e ".[ax-llm]"`.
For JavaScript-rendered sites, also install the headless browser with
`python -m playwright install chromium`. An installed Chrome or Edge is used
as a fallback on local Windows machines. The server renders only HTML pages
whose static body is empty and contains scripts; ordinary sites keep the
existing HTTP collection path. Browser resources are fetched through the same
public-address and robots checks, limited to the site's exact www alias pair.
The renderer blocks writes, third-party resources, frames and service workers;
browser profiles and cookies are discarded after each analysis. Each page has
a 25-second render budget, a 60-request cap and the existing 3 MB resource cap.
An analysis is limited to 20 MB of fetched render resources. Rendering failure
has its own error code and remains in the separate diagnostic log.

```powershell
oss-web --workbook "PATH_TO_V0.3.xlsx"
```

Open `http://127.0.0.1:8765` and enter a public demand-company homepage URL.
The service requires no login or account. Results remain only in the current
page's memory and are cleared on reload. There is no search-history button or
routine result storage. Incomplete/error cases alone retain a separate local
diagnostic snapshot for later investigation, as described below. The retired
`oss-search-history` IndexedDB database
is deleted when the page opens; unrelated browser databases are untouched.
The **기업 이해** section presents one short paragraph combining the company's
business and core activities. The underlying fact extraction and independent
grounding audit still retain source quotes internally. This path requires an
OpenAI API key in `.env` and does not write to Supabase.

**AI로 개선할 수 있는 업무** shows up to three audited work ideas. Each card
answers what it helps with, what gets easier, and what to check before adoption.
Selecting a card displays up to three suppliers for that specific work, rather
than taking three suppliers across all work ideas. A supplier can appear under
multiple work ideas with different explanations. Suppliers without corroborated,
complete pool profiles remain excluded.

A separate model pass writes four buyer-facing supplier answers (why this
supplier, how to use it, how work changes, and what to ask). An independent audit
checks actual supplier capability against the specific buyer work. A shared Task
ID alone cannot establish domain suitability. Pairs without supported solution
names, source quotations or an approving audit are excluded. These two model
calls add to analysis time. Contact details are shown separately, and original
solution descriptions are available under **상세정보**. Source IDs and internal
review diagnostics are not shown on the result screen.

**보고서 다운로드**, opposite **추천 결과**, downloads an A4 Korean PDF of the
current result. It includes the company summary, every recommended work and its
related suppliers, all four supplier answers, contact details, and expanded
solution descriptions, regardless of the work selected on screen. The button
is disabled before a result exists, during analysis, and while exporting.

`POST /api/report.pdf` accepts the screen's display fields and returns a PDF
attachment. ReportLab builds it in memory without another crawl, AI request,
database query, or server-side file/result storage. Korean filenames include
the report generation date in Korean time. The bundled Nanum Gothic regular
and bold fonts are embedded in the PDF and distributed under the SIL Open Font
License in `src/oss/fonts/OFL.txt`. Reinstall the project dependencies after
updating an older checkout: `python -m pip install -e ".[ax-llm]"`.

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

## Search processing times

Every accepted `POST /api/analyze` records the elapsed server processing time
from request receipt through the response write, including crawling, AI calls,
supplier lookup and result assembly. Durations use a monotonic clock; timestamps
use Korean time. Browser network transfer and rendering are not included.

- `reports/search-timing/searches.jsonl`: one entry per completed search,
  containing timestamps, duration in seconds, success/failure, HTTP status,
  and code revision. No URL, company name, search content, result, or user
  identifier is stored.
- `reports/search-timing/summary.json`: cumulative search counts and mean
  duration, plus separate means for successful and failed searches. Means are
  `null` until samples exist. The summary is updated after each search and
  rebuilt from the timing log on server restart.

Demo requests, PDF exports, health checks and malformed/missing-URL requests
are excluded. Concurrent requests are serialized only when writing the log.
These local operational files survive `dev.cmd` restarts and are ignored by
Git. This timing log does not restore the removed search-history feature.

## Empty output diagnostics

If any display field in **01.기업 이해**, **02.AI로 개선할 수 있는 업무**, or
**03.추천 공급기업** is missing, a case is recorded in `reports/empty-output/`.
This includes empty sections, an individual work without suppliers, missing
card answers/contact fields, and absent underlying values hidden by generic
screen fallback messages. An unselected supplier panel is a normal UI state
and is not an incident. Failed accepted analyses also retain the failed stage.

- `index.jsonl`: incident time, input URL, affected section/field paths, code
  revision, HTTP status, and the corresponding detail filename.
- `case-*.json`: the input page texts actually selected for analysis, business
  and AX quality/rejection evidence, profile eligibility and missing-field
  diagnostics, matching exclusions, supplier explanation drafts and audit
  decisions, and a diagnostic output snapshot. Contact profile values and
  server credentials are not included.

Only incomplete/error cases are saved; normal complete results are not.
The diagnostic files are local, ignored by Git, survive server restarts, and
are not exposed by the result API or the static web server. No extra AI call,
crawl or database query is performed to create a case. Logging does not relax
existing validation or alter supplier selection. See
[the investigation guide](docs/empty-output-diagnostics.md).

## Tests

The source contract test runs when `OSS_WORKBOOK_PATH` points to the workbook:

```powershell
python -m pip install -e ".[ax-llm,cloud,test]"
$env:OSS_WORKBOOK_PATH = "PATH_TO_V0.3.xlsx"
python -m unittest discover -s tests -v
```

With the local server running, Node.js, Playwright and Microsoft Edge available:

```powershell
node tests/test_frontend.cjs
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
