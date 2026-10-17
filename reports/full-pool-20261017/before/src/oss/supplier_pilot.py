"""Bounded, resumable crawl of supplier homepages from a pool snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from http.client import InvalidURL
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from .crawler import RateLimited, RobotsDisallowed, crawl_site


def _crawl_record(
    record: dict, output_dir: Path, max_pages: int, refresh: bool,
    host_locks: dict[str, Lock],
) -> dict:
    supplier_id = record["sply_pool_no"]
    path = output_dir / f"{supplier_id}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    urls = record["homepage_urls"]
    result = {
        "sply_pool_no": supplier_id,
        "name": record["name"],
        "homepage_raw": record["homepage_raw"],
        "source_url": urls[0] if urls else None,
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "status": "missing_url" if not urls else "pending",
        "pages": [],
        "error": None,
        "site_attempts": [],
    }
    if urls:
        def save_raw(url: str, raw: bytes) -> None:
            name = hashlib.sha256(url.encode("utf-8")).hexdigest() + ".html"
            raw_dir = output_dir / "raw" / str(supplier_id)
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / name).write_bytes(raw)

        seen_pages: set[str] = set()
        for url in urls:
            attempt = {"url": url, "status": "pending", "error": None, "page_count": 0}
            with host_locks[urlsplit(url).hostname or url]:
                try:
                    pages = crawl_site(url, max_pages=max_pages, on_page=save_raw)
                    for page in pages:
                        if page.url not in seen_pages:
                            result["pages"].append(asdict(page))
                            seen_pages.add(page.url)
                    attempt["page_count"] = len(pages)
                    attempt["status"] = "with_pages" if pages else "no_pages"
                except RobotsDisallowed as error:
                    attempt["status"], attempt["error"] = "robots_disallowed", str(error)
                except RateLimited as error:
                    attempt["status"], attempt["error"] = "rate_limited", str(error)
                except (OSError, RuntimeError, ValueError, InvalidURL) as error:
                    attempt["status"], attempt["error"] = "failed", str(error)
                except Exception as error:
                    attempt["status"] = "failed"
                    attempt["error"] = f"{type(error).__name__}: {error}"
                time.sleep(0.5)
            result["site_attempts"].append(attempt)
        statuses = {attempt["status"] for attempt in result["site_attempts"]}
        if result["pages"]:
            result["status"] = "with_pages"
        elif "failed" in statuses:
            result["status"] = "failed"
        elif "rate_limited" in statuses:
            result["status"] = "rate_limited"
        elif "robots_disallowed" in statuses:
            result["status"] = "robots_disallowed"
        else:
            result["status"] = "no_pages"
        result["error"] = "; ".join(
            attempt["error"] for attempt in result["site_attempts"] if attempt["error"]
        ) or None
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return result


def crawl_suppliers(
    prepared_path: Path, output_dir: Path, *, count: int, max_pages: int = 6,
    refresh: bool = False, workers: int = 4,
) -> dict:
    if not 1 <= workers <= 8:
        raise ValueError("workers must be between 1 and 8")
    records = json.loads(prepared_path.read_text(encoding="utf-8"))[:count]
    output_dir.mkdir(parents=True, exist_ok=True)
    hosts = {urlsplit(url).hostname or url for record in records for url in record["homepage_urls"]}
    host_locks = {host: Lock() for host in hosts}
    summary = {
        "attempted": 0, "with_pages": 0, "no_pages": 0,
        "failed": 0, "robots_disallowed": 0, "rate_limited": 0, "missing_url": 0,
        "pages_collected": 0,
    }
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for result in executor.map(
            lambda record: _crawl_record(record, output_dir, max_pages, refresh, host_locks), records,
        ):
            summary["attempted"] += 1
            summary[result["status"]] += 1
            summary["pages_collected"] += len(result["pages"])
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Pilot crawl of supplier homepages")
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--max-pages", type=int, default=6)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be positive")
    print(json.dumps(crawl_suppliers(
        args.prepared, args.output_dir, count=args.count, max_pages=args.max_pages,
        refresh=args.refresh, workers=args.workers,
    ), indent=2))


if __name__ == "__main__":
    main()
