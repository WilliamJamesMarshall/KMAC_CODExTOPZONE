"""Build repeatable SQL batches for importing a verified pool snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from pathlib import Path
from urllib.parse import urlsplit


SOURCE_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://pms.ai-voucher.or.kr/supply/pool")


def supplier_uuid(year: int, sply_pool_no: int) -> str:
    return str(uuid.uuid5(SOURCE_NAMESPACE, f"AI바우처:{year}:{sply_pool_no}"))


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _source_rows(records: list[dict], prepared: list[dict], year: int) -> list[dict]:
    by_id = {item["sply_pool_no"]: item for item in prepared}
    if len(by_id) != len(records):
        raise ValueError("Prepared record count does not match source records")
    result = []
    for record in records:
        pool_no = record["splyPoolNo"]
        item = by_id[pool_no]
        url = item["homepage_urls"][0] if len(item["homepage_urls"]) == 1 else None
        founded = str(record.get("fndnYmd") or "")[:4]
        raw = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        result.append({
            "supplier_id": supplier_uuid(year, pool_no),
            "sply_pool_no": pool_no,
            "canonical_name": record["splyCmpNm"],
            "homepage_url": url,
            "homepage_host": urlsplit(url).hostname if url else None,
            "founded_year": int(founded) if founded.isdigit() and 1800 <= int(founded) <= 2100 else None,
            "region": record.get("splyAddrSido"),
            "specialization": record.get("specialization"),
            "ai_solution_text": record.get("aiSolution"),
            "homepage_raw": record.get("splyCmpHmpg"),
            "source_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "raw_record": record,
        })
    return result


def _batch_sql(rows: list[dict], year: int, fetched_at: str) -> str:
    payload = _sql_string(json.dumps(rows, ensure_ascii=False, separators=(",", ":")))
    source = f"""select * from jsonb_to_recordset({payload}::jsonb) as x(
    supplier_id uuid, sply_pool_no bigint, canonical_name text,
    homepage_url text, homepage_host text, founded_year integer, region text,
    specialization text, ai_solution_text text, homepage_raw text,
    source_hash text, raw_record jsonb
  )"""
    return f"""begin;
insert into public.suppliers (
  id, canonical_name, legal_name, homepage_url, homepage_host, founded_year, region
)
select supplier_id, canonical_name, canonical_name, homepage_url, homepage_host,
       founded_year, region
from ({source}) as src
on conflict (id) do nothing;

insert into public.pool_entries (
  supplier_id, source_program, source_year, sply_pool_no, source_url,
  source_hash, raw_record, specialization, ai_solution_text, homepage_raw, fetched_at
)
select supplier_id, 'AI바우처', {year}, sply_pool_no,
       'https://pms.ai-voucher.or.kr/supply/pool', source_hash, raw_record,
       specialization, ai_solution_text, homepage_raw, {_sql_string(fetched_at)}::timestamptz
from ({source}) as src
on conflict (source_program, source_year, sply_pool_no)
do update set source_hash = excluded.source_hash,
              raw_record = excluded.raw_record,
              specialization = excluded.specialization,
              ai_solution_text = excluded.ai_solution_text,
              homepage_raw = excluded.homepage_raw,
              fetched_at = excluded.fetched_at;
commit;
"""


def _domain_sql(prepared: list[dict], year: int) -> str:
    domains = [
        {
            "supplier_id": supplier_uuid(year, item["sply_pool_no"]),
            "domain": urlsplit(url).hostname,
            "base_url": url,
            "is_primary": len(item["homepage_urls"]) == 1,
        }
        for item in prepared for url in item["homepage_urls"]
    ]
    payload = _sql_string(json.dumps(domains, ensure_ascii=False, separators=(",", ":")))
    return f"""insert into public.supplier_domains
  (supplier_id, domain, base_url, domain_type, is_primary)
select supplier_id, domain, base_url, 'unclassified', is_primary
from jsonb_to_recordset({payload}::jsonb) as x(
  supplier_id uuid, domain text, base_url text, is_primary boolean
)
on conflict (supplier_id, base_url) do update
set last_seen_at = now();
"""


def build_import_batches(snapshot_dir: Path, output_dir: Path, *, batch_size: int = 50) -> dict:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    records = json.loads((snapshot_dir / "records.json").read_text(encoding="utf-8"))
    prepared = json.loads((snapshot_dir / "prepared.json").read_text(encoding="utf-8"))
    if len(records) != manifest["total_elements"]:
        raise ValueError("Snapshot count does not match manifest")
    payload = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if hashlib.sha256(payload.encode("utf-8")).hexdigest() != manifest["record_sha256"]:
        raise ValueError("Snapshot hash does not match manifest")
    rows = _source_rows(records, prepared, manifest["year"])
    output_dir.mkdir(parents=True, exist_ok=True)
    for start in range(0, len(rows), batch_size):
        path = output_dir / f"{start // batch_size + 1:04d}.sql"
        path.write_text(
            _batch_sql(rows[start:start + batch_size], manifest["year"], manifest["fetched_at"]),
            encoding="utf-8",
        )
    domain_count = 0
    for start in range(0, len(prepared), batch_size):
        items = prepared[start:start + batch_size]
        domain_count += sum(len(item["homepage_urls"]) for item in items)
        (output_dir / f"domains-{start // batch_size + 1:04d}.sql").write_text(
            _domain_sql(items, manifest["year"]), encoding="utf-8",
        )
    return {
        "rows": len(rows), "batches": (len(rows) + batch_size - 1) // batch_size,
        "domains": domain_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate pool import SQL batches")
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()
    print(json.dumps(build_import_batches(args.snapshot_dir, args.output_dir, batch_size=args.batch_size)))


if __name__ == "__main__":
    main()
