"""Create idempotent SQL for pilot crawl runs, pages, and source chunks."""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from pathlib import Path

from .pool_import import SOURCE_NAMESPACE, _sql_string, supplier_uuid


def _chunks(text: str, limit: int = 1200) -> list[str]:
    result: list[str] = []
    current = ""
    for paragraph in text.splitlines():
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        while len(paragraph) > limit:
            if current:
                result.append(current)
                current = ""
            result.append(paragraph[:limit])
            paragraph = paragraph[limit:]
        if not paragraph:
            continue
        if len(current) + len(paragraph) + 1 > limit:
            result.append(current)
            current = ""
        current = f"{current}\n{paragraph}" if current else paragraph
    if current:
        result.append(current)
    return result


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _page_type(url: str, title: str) -> str:
    value = f"{url} {title}".lower()
    for kind, hints in (
        ("case_study", ("case", "사례", "portfolio", "project", "구축")),
        ("solution", ("solution", "솔루션")),
        ("product", ("product", "제품")),
        ("service", ("service", "서비스")),
        ("company", ("about", "company", "회사소개")),
    ):
        if any(hint in value for hint in hints):
            return kind
    return "unknown"


def _crawl_rows(files: list[Path], year: int) -> tuple[list[dict], list[dict], list[dict]]:
    runs: list[dict] = []
    pages: list[dict] = []
    chunks: list[dict] = []
    for path in files:
        item = json.loads(path.read_text(encoding="utf-8"))
        supplier_id = supplier_uuid(year, item["sply_pool_no"])
        run_id = str(uuid.uuid5(SOURCE_NAMESPACE, f"crawl:{item['sply_pool_no']}:{item['crawled_at']}"))
        runs.append({
            "id": run_id,
            "supplier_id": supplier_id,
            "started_at": item["crawled_at"],
            "status": item["status"],
            "pages_fetched": len(item["pages"]),
            "robots_allowed": (
                False if item["status"] == "robots_disallowed"
                else True if item["status"] in ("with_pages", "no_pages") else None
            ),
            "error_message": (item.get("error") or "").replace("\x00", "") or None,
        })
        seen_urls: set[str] = set()
        for page in item["pages"]:
            url = page["url"].replace("\x00", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            page_id = str(uuid.uuid5(uuid.UUID(run_id), url))
            clean_text = page["text"].replace("\x00", "")
            pages.append({
                "id": page_id,
                "supplier_id": supplier_id,
                "crawl_run_id": run_id,
                "url": url,
                "page_type": _page_type(url, page["title"]),
                "title": page["title"].replace("\x00", ""),
                "clean_text": clean_text,
                "content_hash": _sha(clean_text),
                "crawled_at": item["crawled_at"],
            })
            for index, text in enumerate(_chunks(clean_text)):
                chunks.append({
                    "page_id": page_id,
                    "supplier_id": supplier_id,
                    "chunk_index": index,
                    "chunk_text": text,
                    "content_hash": _sha(text),
                })
    return runs, pages, chunks


def _insert_sql(rows: list[dict], table: str, columns: str, types: str) -> str:
    if not rows:
        return ""
    payload = _sql_string(json.dumps(rows, ensure_ascii=False, separators=(",", ":")))
    return f"""insert into public.{table} ({columns})
select {columns} from jsonb_to_recordset({payload}::jsonb) as x({types})
on conflict do nothing;
"""


def build_crawl_import(crawl_dir: Path, output_dir: Path, *, year: int, batch_size: int = 10) -> dict:
    files = sorted(path for path in crawl_dir.glob("*.json") if path.stem.isdigit())
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    totals = {"runs": 0, "pages": 0, "chunks": 0, "batches": 0}
    for start in range(0, len(files), batch_size):
        runs, pages, chunks = _crawl_rows(files[start:start + batch_size], year)
        sql = "begin;\n"
        for run in runs:
            run["crawler_version"] = "OSS-AX-Research/0.1"
            run["pages_discovered"] = run["pages_fetched"]
        sql += _insert_sql(
            runs, "crawl_runs",
            "id, supplier_id, started_at, status, crawler_version, pages_discovered, pages_fetched, robots_allowed, error_message",
            "id uuid, supplier_id uuid, started_at timestamptz, status text, "
            "crawler_version text, pages_discovered integer, pages_fetched integer, robots_allowed boolean, error_message text",
        )
        sql += _insert_sql(
            pages, "web_pages",
            "id, supplier_id, crawl_run_id, url, page_type, title, clean_text, content_hash, crawled_at",
            "id uuid, supplier_id uuid, crawl_run_id uuid, url text, page_type text, title text, "
            "clean_text text, content_hash text, crawled_at timestamptz",
        )
        sql += _insert_sql(
            chunks, "page_chunks",
            "page_id, supplier_id, chunk_index, chunk_text, content_hash",
            "page_id uuid, supplier_id uuid, chunk_index integer, chunk_text text, content_hash text",
        )
        sql += "commit;\n"
        (output_dir / f"{start // batch_size + 1:04d}.sql").write_text(sql, encoding="utf-8")
        totals["runs"] += len(runs)
        totals["pages"] += len(pages)
        totals["chunks"] += len(chunks)
        totals["batches"] += 1
    return totals


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate SQL from supplier crawl files")
    parser.add_argument("--crawl-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--batch-size", type=int, default=10)
    args = parser.parse_args()
    print(json.dumps(build_crawl_import(
        args.crawl_dir, args.output_dir, year=args.year, batch_size=args.batch_size,
    )))


if __name__ == "__main__":
    main()
