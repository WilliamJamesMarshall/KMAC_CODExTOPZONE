# OSS Capability Knowledge Base v0.3 audit

Source: `AX_AI바우처_5범주_600개기업_과업분류_v0.3.xlsx`

SHA-256: `5A501EABC9D6D61F1F429172342F248BE04B9438A50CF93570A6AA6E175A1CF9`

The workbook is read in memory. This repository does not copy or modify it.

| Sheet | Data rows |
| --- | ---: |
| 과업목록 | 147 |
| 솔루션목록 | 169 |
| 활동연결 | 274 |
| 통합대조표 | 175 |
| 세부활동근거 | 383 |
| 기업목록 | 136 |
| 설명원문 | 1,505 |
| AI스캔 | 600 |
| 스캔근거 | 2,566 |
| 범위변경 | 30 |
| 이전스캔 | 30 |
| 분류규칙 | 29 |

All 147 task rows, 169 solution rows, 274 activity links, and 600 AI scan
rows have `검토상태 = 미검토`. Detailed coding is therefore not presented as
independent homepage verification.

Three activity links point to IDs absent from the active task list:

| Link | Excel row | Task | Treatment |
| --- | ---: | --- | --- |
| L0023 | 28 | J005 | Preserve in audit; exclude from active lookup |
| L0041 | 46 | J007 | Preserve in audit; exclude from active lookup |
| L0056 | 59 | J007 | Preserve in audit; exclude from active lookup |

`범위변경` records J005/J007 as needing clarification of business purpose
before demand matching. The active detailed-link count is 271. Old-ID aliases
also refer to inactive J005, J007, J037, J038, and J040; the loader preserves
their history but does not resolve them to an active task.

The 136 detailed-company IDs and 600 scan-company IDs overlap for 74 IDs. The
in-memory catalog has 662 distinct source IDs, which is **not** a count of
unique legal companies. Exact normalized names reveal 17 potential cross-ID
duplicates. Candidate scores stay separate until company identity is reviewed.

All expanded `설명원문` references in `활동연결` and `세부활동근거` resolve to a source
row after splitting semicolon-separated IDs. The source quotes and IDs remain
available for later provenance storage.

## Implementation decisions

- `과업목록` is the active Task ID set. Out-of-scope IDs do not enter matches.
- `스캔근거` is a candidate signal only.
- `활동연결` is detailed but still unreviewed; its source is the voucher
  description, not a visited supplier homepage.
- A new official-site function claim is labeled `homepage_unreviewed` until
  a reviewer confirms its mapping.
- Project quotes are not projects. Structured project fields require explicit
  source text and remain unreviewed.
