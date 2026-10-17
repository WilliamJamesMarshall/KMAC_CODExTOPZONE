"""Save an auditable snapshot of the public AI voucher supplier pool."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


POOL_URL = "https://pms.ai-voucher.or.kr/supply/pool"
LIST_URL = f"{POOL_URL}/list"
PAGE_SIZE = 10
USER_AGENT = "OSS-AX-Research/0.1 (+public supplier pool snapshot)"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _fetch_page(year: int, page: int) -> dict:
    params = {
        "area": "", "exptFld": "", "keyword": "", "year": year,
        "approvalStatus": "1", "applyVoucher": "1", "page": page, "size": PAGE_SIZE,
    }
    request = Request(f"{LIST_URL}?{urlencode(params)}", headers={"User-Agent": USER_AGENT})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=20) as response:
                return json.load(response)
        except (OSError, ValueError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def _validate_page(data: dict, page: int, total: int, pages: int) -> None:
    if not isinstance(data, dict) or not isinstance(data.get("content"), list):
        raise ValueError(f"Page {page} has no supplier list")
    if data.get("totalElements") != total or data.get("totalPages") != pages:
        raise ValueError(f"Page {page} changed total count during collection")
    expected = PAGE_SIZE if page < pages - 1 else total - PAGE_SIZE * (pages - 1)
    if len(data["content"]) != expected:
        raise ValueError(f"Page {page} has {len(data['content'])} rows; expected {expected}")


def snapshot_pool(year: int, output_dir: Path, *, refresh: bool = False, delay: float = 0.5) -> dict:
    """Fetch each page once, resume from saved pages, and verify source IDs."""
    if year < 2000 or delay < 0:
        raise ValueError("Invalid year or delay")
    output_dir.mkdir(parents=True, exist_ok=True)
    first_path = output_dir / "pages" / "0000.json"
    first = (
        json.loads(first_path.read_text(encoding="utf-8"))
        if first_path.exists() and not refresh else _fetch_page(year, 0)
    )
    total, pages = first.get("totalElements"), first.get("totalPages")
    if not isinstance(total, int) or not isinstance(pages, int) or total <= 0 or pages <= 0:
        raise ValueError("Source did not return a valid count")
    _validate_page(first, 0, total, pages)
    if refresh or not first_path.exists():
        _write_json(first_path, first)

    records: list[dict] = list(first["content"])
    for page in range(1, pages):
        path = output_dir / "pages" / f"{page:04d}.json"
        if path.exists() and not refresh:
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            time.sleep(delay)
            data = _fetch_page(year, page)
            _validate_page(data, page, total, pages)
            _write_json(path, data)
        _validate_page(data, page, total, pages)
        records.extend(data["content"])

    ids = [row.get("splyPoolNo") for row in records]
    if len(records) != total or any(not isinstance(value, int) for value in ids):
        raise ValueError("Supplier count or source ID is invalid")
    if len(set(ids)) != total:
        raise ValueError("Duplicate source supplier IDs in snapshot")
    payload = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    manifest = {
        "source_url": POOL_URL,
        "source_program": "AI바우처",
        "year": year,
        "fetched_at": datetime.fromtimestamp(first_path.stat().st_mtime, timezone.utc).isoformat(),
        "total_elements": total,
        "total_pages": pages,
        "record_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }
    _write_json(output_dir / "records.json", records)
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Snapshot the public AI voucher supplier pool")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--refresh", action="store_true", help="Refetch already saved pages")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between requests")
    args = parser.parse_args()
    print(json.dumps(snapshot_pool(args.year, args.output_dir, refresh=args.refresh, delay=args.delay), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
