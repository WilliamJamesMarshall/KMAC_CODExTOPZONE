"""Extract only explicitly named, unreviewed solutions from pool descriptions."""

from __future__ import annotations

import argparse
import json
import re
import uuid
from pathlib import Path

from .pool_import import SOURCE_NAMESPACE, _sql_string, supplier_uuid


SOLUTION_LABEL = re.compile(
    r"(?im)^[ \t]*(?:[□○ㅇoO*\-]\s*)?(?:\d+[.)]\s*)?(?:AI\s*)?"
    r"(?:솔루션|제품)\s*명\s*\d*\s*[:：]\s*([^\r\n]+)"
)


def named_solutions(description: str) -> list[tuple[str, str]]:
    matches = list(SOLUTION_LABEL.finditer(description))
    result: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        name = match.group(1).strip(" \t-*□○ㅇ")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(description)
        source_text = description[match.start():end].strip()
        if 2 <= len(name) <= 180 and len(source_text) - len(match.group(0)) >= 15:
            result.append((name, source_text))
    return result


def build_pool_solution_sql(snapshot_dir: Path, output_dir: Path, *, batch_size: int = 50) -> dict:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    records = json.loads((snapshot_dir / "records.json").read_text(encoding="utf-8"))
    year = manifest["year"]
    rows: list[dict] = []
    for record in records:
        for index, (name, text) in enumerate(named_solutions(record.get("aiSolution") or "")):
            pool_no = record["splyPoolNo"]
            rows.append({
                "id": str(uuid.uuid5(SOURCE_NAMESPACE, f"pool-solution:{year}:{pool_no}:{index}")),
                "supplier_id": supplier_uuid(year, pool_no),
                "sply_pool_no": pool_no,
                "solution_name": name,
                "description": text,
            })
    output_dir.mkdir(parents=True, exist_ok=True)
    for start in range(0, len(rows), batch_size):
        payload = _sql_string(json.dumps(rows[start:start + batch_size], ensure_ascii=False, separators=(",", ":")))
        sql = f"""insert into public.supplier_solutions
  (id, supplier_id, solution_name, description, source_pool_entry_id, status, verification_status)
select x.id, x.supplier_id, x.solution_name, x.description, p.id,
       'candidate', 'unreviewed'
from jsonb_to_recordset({payload}::jsonb) as x(
  id uuid, supplier_id uuid, sply_pool_no bigint, solution_name text, description text
)
join public.pool_entries p on p.sply_pool_no = x.sply_pool_no
  and p.source_program = 'AI바우처' and p.source_year = {year}
on conflict (id) do nothing;
"""
        (output_dir / f"{start // batch_size + 1:04d}.sql").write_text(sql, encoding="utf-8")
    return {"candidate_solutions": len(rows), "suppliers": len({r["supplier_id"] for r in rows})}


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract explicitly named pool solution candidates")
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()
    print(json.dumps(build_pool_solution_sql(
        args.snapshot_dir, args.output_dir, batch_size=args.batch_size,
    )))


if __name__ == "__main__":
    main()
