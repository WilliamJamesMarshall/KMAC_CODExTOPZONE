"""Audit the 2026 voucher pool against suppliers the OSS UI can recommend.

This is read-only: it reproduces SupplierProfileClient's identity decision from
the saved, checksum-verified pool snapshot and the v0.3 workbook. It does not
make a claim that an unmatched old supplier is absent from every voucher year.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from oss.identity import company_name_key
from oss.supplier_profile import SupplierProfileClient, _host
from oss.workbook import load_knowledge_base


FIELD_MAP = {
    "specialization": "specialization",
    "ai_solution_description": "aiSolution",
    "address": "splyCmpAddr",
    "phone": "bizTelNo",
    "representative": "splyCmpRpstNm",
}


def nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def audit(snapshot_dir: Path, workbook_path: Path) -> dict:
    manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    records = json.loads((snapshot_dir / "records.json").read_text(encoding="utf-8"))
    prepared = json.loads((snapshot_dir / "prepared.json").read_text(encoding="utf-8"))
    payload = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    if digest != manifest["record_sha256"] or len(records) != manifest["total_elements"]:
        raise ValueError("Pool snapshot count or SHA-256 does not match manifest")
    raw_by_no = {row["splyPoolNo"]: row for row in records}
    if len(raw_by_no) != len(records) or len(prepared) != len(records):
        raise ValueError("Pool ID or prepared row count is inconsistent")

    kb = load_knowledge_base(workbook_path)
    detailed_ids = {cap.supplier_id for cap in kb.detailed_capabilities}
    by_name = defaultdict(list)
    by_host = defaultdict(list)
    pool_rows = []
    for row in prepared:
        no = row["sply_pool_no"]
        raw = raw_by_no[no]
        homepage_url = row["homepage_urls"][0] if len(row["homepage_urls"]) == 1 else None
        candidate = {"id": str(no), "canonical_name": row["name"],
                     "homepage_url": homepage_url}
        entry = {"sply_pool_no": no, "ai_solution_text": row["ai_solution_text"],
                 "raw_record": raw}
        by_name[company_name_key(row["name"])].append((candidate, entry))
        if homepage_url:
            host = urlsplit(homepage_url).hostname.removeprefix("www.")
            by_host[host].append((candidate, entry))
        missing = [
            field for field, source in FIELD_MAP.items()
            if not nonempty(row["specialization"] if source == "specialization"
                            else raw.get(source))
        ]
        pool_rows.append({
            "sply_pool_no": no, "name": row["name"], "missing_profile_fields": missing,
            "url_status": row["url_status"], "has_recommendable_detailed_name":
            any(company_name_key(kb.suppliers[sid].name) == company_name_key(row["name"])
                for sid in detailed_ids),
        })

    recommendable = []
    for sid in sorted(detailed_ids):
        supplier = kb.suppliers[sid]
        item = {"supplier_id": sid, "name": supplier.name}
        same_name = by_name.get(company_name_key(supplier.name), [])
        corroborated = [
            (candidate, entry) for candidate, entry in same_name
            if SupplierProfileClient._corroborated(item, candidate, entry, kb)
        ]
        if not same_name:
            status = "not_found"
        elif not corroborated:
            status = "needs_review"
        elif len(corroborated) > 1:
            status = "ambiguous"
        else:
            status = "matched"
        workbook_host = _host(supplier.homepage_url)
        host_candidates = by_host.get(workbook_host, []) if workbook_host else []
        recommendable.append({
            "supplier_id": sid, "name": supplier.name,
            "workbook_homepage": supplier.homepage_url,
            "profile_status": status,
            "same_name_pool_ids": [e["sply_pool_no"] for _, e in same_name],
            "same_name_pool_names": [c["canonical_name"] for c, _ in same_name],
            "corroborated_pool_ids": [e["sply_pool_no"] for _, e in corroborated],
            "same_homepage_pool_ids": [e["sply_pool_no"] for _, e in host_candidates],
            "same_homepage_pool_names": [c["canonical_name"] for c, _ in host_candidates],
        })

    return {
        "snapshot": {"year": manifest["year"], "source_url": manifest["source_url"],
                     "fetched_at": manifest["fetched_at"], "record_sha256": digest},
        "counts": {
            "pool_entries": len(pool_rows),
            "pool_missing_any_profile_field": sum(bool(x["missing_profile_fields"]) for x in pool_rows),
            "pool_missing_field_counts": dict(Counter(
                field for row in pool_rows for field in row["missing_profile_fields"])),
            "pool_url_status": dict(Counter(x["url_status"] for x in pool_rows)),
            "workbook_suppliers": len(kb.suppliers),
            "recommendable_suppliers": len(recommendable),
            "recommendable_profile_status": dict(Counter(
                x["profile_status"] for x in recommendable)),
        },
        "recommendable_suppliers": recommendable,
        "pool_entries": pool_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.snapshot_dir, args.workbook)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps(result["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
