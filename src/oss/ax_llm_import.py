"""Build idempotent Supabase SQL from validated, source-quoted LLM results."""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from pathlib import Path

from .ax_llm import PROMPT_VERSION, build_sources, validate_matches
from .pool_import import _sql_string
from .workbook import load_knowledge_base


def build_llm_import(workbook_path: Path, prepared_path: Path, crawl_dir: Path,
                     results_dir: Path, output_dir: Path, *, batch_size: int = 50) -> dict:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    tasks = load_knowledge_base(workbook_path).tasks
    prepared = {item["sply_pool_no"]: item for item in
                json.loads(prepared_path.read_text(encoding="utf-8"))}
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, f"AX-LLM:{PROMPT_VERSION}")
    rows: list[dict] = []
    processed = 0
    empty = 0
    for path in sorted(results_dir.glob("*.json")):
        if not path.stem.isdigit():
            continue
        result = json.loads(path.read_text(encoding="utf-8"))
        pool_no = int(path.stem)
        if result["sply_pool_no"] != pool_no or pool_no not in prepared:
            raise ValueError(f"Result identity mismatch: {path}")
        if result["prompt_version"] != PROMPT_VERSION:
            raise ValueError(f"Unexpected prompt version: {path}")
        sources = build_sources(prepared[pool_no], crawl_dir)
        hashes = {source_id: hashlib.sha256(source["text"].encode("utf-8")).hexdigest()
                  for source_id, source in sources.items()}
        if result["source_hashes"] != hashes:
            raise ValueError(f"Source content changed after extraction: {path}")
        matches = validate_matches({"matches": result["matches"]}, tasks, sources)
        processed += 1
        empty += not matches
        for match in matches:
            source = sources[match["source_id"]]
            rows.append({
                "id": str(uuid.uuid5(namespace, f"{pool_no}:{match['task_id']}:{match['source_id']}")),
                "sply_pool_no": pool_no,
                "task_id": match["task_id"],
                "source_kind": source["kind"],
                "source_url": source["url"],
                "evidence_text": match["quote"],
                "evidence_strength": 2 if source["kind"] == "website" else 1,
                "extractor_model": result["model"],
            })
    output_dir.mkdir(parents=True, exist_ok=True)
    for start in range(0, len(rows), batch_size):
        payload = _sql_string(json.dumps(rows[start:start + batch_size], ensure_ascii=False,
                                         separators=(",", ":")))
        sql = f"""begin;
with x as (
  select * from jsonb_to_recordset({payload}::jsonb) as r(
    id uuid, sply_pool_no bigint, task_id text, source_kind text,
    source_url text, evidence_text text, evidence_strength smallint,
    extractor_model text)
)
insert into public.capability_evidence
  (id, supplier_id, task_id, pool_entry_id, page_id, evidence_text,
   evidence_type, evidence_strength, verification_status, mapping_method,
   extractor_model, extractor_version, prompt_version)
select x.id, p.supplier_id, x.task_id,
       case when x.source_kind = 'pool' then p.id else null end,
       case when x.source_kind = 'website' then w.id else null end,
       x.evidence_text, 'company_description', x.evidence_strength,
       'candidate', 'llm_extracted', x.extractor_model, 'v1', '{PROMPT_VERSION}'
from x
join public.pool_entries p on p.source_program = 'AI바우처'
  and p.source_year = 2026 and p.sply_pool_no = x.sply_pool_no
join public.ax_tasks t on t.task_id = x.task_id
left join lateral (
  select page.id, page.clean_text from public.web_pages page
  where page.supplier_id = p.supplier_id and page.url = x.source_url
  order by page.crawled_at desc limit 1
) w on x.source_kind = 'website'
where (x.source_kind = 'pool' and position(
         regexp_replace(x.evidence_text, '[[:space:]]', '', 'g') in
         regexp_replace(p.ai_solution_text, '[[:space:]]', '', 'g')) > 0)
   or (x.source_kind = 'website' and w.id is not null and position(
         regexp_replace(x.evidence_text, '[[:space:]]', '', 'g') in
         regexp_replace(w.clean_text, '[[:space:]]', '', 'g')) > 0)
on conflict (id) do nothing;
commit;
"""
        (output_dir / f"{start // batch_size + 1:04d}.sql").write_text(sql, encoding="utf-8")
    audit = {
        "processed_suppliers": processed,
        "suppliers_with_no_match": empty,
        "candidate_evidence": len(rows),
        "pool_quotes": sum(row["source_kind"] == "pool" for row in rows),
        "website_quotes": sum(row["source_kind"] == "website" for row in rows),
        "batches": (len(rows) + batch_size - 1) // batch_size,
    }
    (output_dir / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate LLM AX results and create SQL batches")
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--crawl-dir", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()
    print(json.dumps(build_llm_import(args.workbook, args.prepared, args.crawl_dir,
                                      args.results_dir, args.output_dir,
                                      batch_size=args.batch_size), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
