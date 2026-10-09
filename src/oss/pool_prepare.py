"""Normalize pool website fields without changing their source text."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


URL_PATTERN = re.compile(
    r"(?:https?://)?(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}"
    r"(?::\d+)?(?:/[^\s,，()<>]*)?",
    re.IGNORECASE,
)


def website_urls(raw: str | None) -> list[str]:
    """Extract plausible public URLs from messy, sometimes annotated pool fields."""
    found: list[str] = []
    raw = raw or ""
    for match in URL_PATTERN.finditer(raw):
        if (match.start() and raw[match.start() - 1] == "@") or raw[match.end():match.end() + 1] == "@":
            continue
        candidate = match.group().rstrip("./;:·。")
        if not candidate.startswith(("http://", "https://")):
            candidate = "https://" + candidate
        parts = urlsplit(candidate)
        if parts.username or parts.password or parts.port not in (None, 80, 443):
            continue
        if parts.hostname == "pms.ai-voucher.or.kr":
            continue
        normalized = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", ""))
        if normalized not in found:
            found.append(normalized)
    return found


def prepare_records(records: list[dict]) -> tuple[list[dict], dict]:
    prepared: list[dict] = []
    stats: Counter[str] = Counter()
    for record in records:
        raw = record.get("splyCmpHmpg") or ""
        urls = website_urls(raw)
        if not raw.strip():
            status = "missing"
        elif not urls:
            status = "invalid"
        elif len(urls) > 1:
            status = "multiple"
        elif not raw.strip().startswith(("http://", "https://")):
            status = "scheme_added"
        else:
            status = "single"
        stats[status] += 1
        prepared.append({
            "sply_pool_no": record["splyPoolNo"],
            "name": record.get("splyCmpNm"),
            "specialization": record.get("specialization"),
            "ai_solution_text": record.get("aiSolution"),
            "homepage_raw": raw,
            "homepage_urls": urls,
            "url_status": status,
        })
    return prepared, {"total": len(prepared), "url_status": dict(stats)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare public supplier pool website fields")
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records = json.loads(args.records.read_text(encoding="utf-8"))
    prepared, audit = prepare_records(records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(prepared, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
