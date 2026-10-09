from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .analysis import analyze_demand_pages, analyze_supplier_pages
from .crawler import crawl_site
from .matching import match_suppliers
from .models import DemandTask, Evidence, WebPage
from .portfolio import find_project_quotes
from .workbook import load_knowledge_base


def _load_pages(path: str) -> list[WebPage]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Page input must be a JSON list")
    return [WebPage(**item) for item in data]


def _output(value: object, destination: str | None) -> None:
    serialized = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if destination:
        Path(destination).write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)


def main() -> None:
    parser = argparse.ArgumentParser(description="OSS AX task matching logic")
    parser.add_argument("--workbook", required=True, help="Path to the v0.3 source workbook")
    parser.add_argument("--output", help="Optional UTF-8 JSON output path")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("audit", help="Inspect source counts and unresolved references")

    candidates = commands.add_parser("candidates", help="Lookup provisional suppliers by AX task ID")
    candidates.add_argument("--task", required=True)
    candidates.add_argument("--limit", type=int, default=10)
    candidates.add_argument("--exclude-scan", action="store_true")

    analyze = commands.add_parser("analyze", help="Analyze supplied website pages or a public URL")
    source = analyze.add_mutually_exclusive_group(required=True)
    source.add_argument("--demand-pages", help="UTF-8 JSON list of {url,title,text}")
    source.add_argument("--demand-url", help="Public website URL")
    analyze.add_argument("--supplier-id", help="Known workbook supplier ID for a homepage pilot")
    analyze.add_argument("--supplier-pages", help="UTF-8 JSON list of supplier pages")
    analyze.add_argument("--supplier-url", help="Public supplier homepage URL")
    analyze.add_argument("--limit", type=int, default=10)

    args = parser.parse_args()
    kb = load_knowledge_base(args.workbook)
    if args.command == "audit":
        _output(kb.audit, args.output)
        return
    if args.command == "candidates":
        if args.task not in kb.tasks:
            parser.error(f"Unknown or inactive task ID: {args.task}")
        demand = DemandTask(
            args.task, "needs_review", 0.4,
            Evidence("", "User-selected task ID", "user_input", args.task, "manual", "미검토"),
            "User-selected task for candidate lookup", "실제 수요 업무와 데이터 준비 상태를 확인했나요?",
        )
        matches = match_suppliers([demand], kb, include_scan=not args.exclude_scan, limit=args.limit)
        _output({"task": asdict(kb.tasks[args.task]), "matches": [asdict(m) for m in matches]}, args.output)
        return

    demand_pages = _load_pages(args.demand_pages) if args.demand_pages else crawl_site(args.demand_url)
    if not demand_pages:
        parser.error("No readable demand-company pages were collected")
    analysis = analyze_demand_pages(demand_pages, kb)
    supplier_capabilities = []
    project_quotes = []
    if args.supplier_pages or args.supplier_url:
        if not args.supplier_id:
            parser.error("--supplier-id is required with supplier pages or URL")
        supplier_pages = _load_pages(args.supplier_pages) if args.supplier_pages else crawl_site(args.supplier_url)
        if not supplier_pages:
            parser.error("No readable supplier pages were collected")
        supplier_capabilities = analyze_supplier_pages(args.supplier_id, supplier_pages, kb)
        project_quotes = find_project_quotes(supplier_pages)
    matches = match_suppliers(analysis.task_candidates, kb, supplier_capabilities, limit=args.limit)
    _output({
        "demand_analysis": asdict(analysis),
        "supplier_homepage_capabilities": [asdict(c) for c in supplier_capabilities],
        "project_quote_candidates": [asdict(e) for e in project_quotes],
        "matches": [asdict(m) for m in matches],
    }, args.output)


if __name__ == "__main__":
    main()
