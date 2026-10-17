"""Add source-linked AI voucher details to workbook supplier recommendations."""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .identity import company_name_key
from .workbook import KnowledgeBase


REQUIRED_PROFILE_FIELDS = (
    "specialization", "ai_solution_description", "address", "phone", "representative",
)


def _text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _host(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value if "://" in value else "https://" + value)
    return parsed.hostname.lower().removeprefix("www.") if parsed.hostname else None


def _compact(value: str) -> str:
    return "".join(value.split())


class SupplierProfileClient:
    """Read private pool records on the server; never return the API key."""

    def __init__(self, url: str | None, secret_key: str | None):
        self.url = (url or "").rstrip("/")
        self.secret_key = secret_key or ""
        self._index: dict[str, list[dict]] | None = None
        self._index_lock = Lock()
        self._catalog = None
        self._catalog_time = 0.0
        self._catalog_lock = Lock()

    def _all_rows(self, table: str, **params: object) -> list[dict]:
        rows = []
        pages = set()
        while True:
            page = self._rows(table, limit=1000, offset=len(rows), **params)
            fingerprint = json.dumps(page, ensure_ascii=False, sort_keys=True)
            if page and fingerprint in pages:
                raise ValueError('Repeated supplier page; pagination did not advance')
            pages.add(fingerprint)
            rows.extend(page)
            if len(page) < 1000:
                return rows

    def catalog(self, kb: KnowledgeBase, *, diagnostics: dict | None = None):
        """Load the whole annual pool atomically; never replace it with a partial page."""
        from .supplier_catalog import build_catalog
        if not self.secret_key or urlparse(self.url).scheme != 'https':
            raise RuntimeError('Supabase 공급기업 원천정보를 조회할 수 없습니다.')
        with self._catalog_lock:
            if self._catalog is None or time.monotonic() - self._catalog_time >= 3600:
                try:
                    suppliers = self._all_rows('suppliers', select='id,canonical_name,homepage_url', order='id.asc')
                    entries = self._all_rows('pool_entries',
                        select='supplier_id,sply_pool_no,specialization,ai_solution_text,raw_record',
                        source_program='eq.AI바우처', source_year='eq.2026', order='sply_pool_no.asc,supplier_id.asc')
                    if not entries:
                        raise ValueError('Empty supplier pool')
                    catalog = build_catalog(suppliers, entries, kb)
                except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as error:
                    logging.warning('Supplier catalogue unavailable: %s', type(error).__name__)
                    raise RuntimeError('Supabase 공급기업 전체 목록을 조회하지 못했습니다.') from error
                self._catalog = catalog
                self._catalog_time = time.monotonic()
            if diagnostics is not None:
                diagnostics.update(self._catalog.summary())
                diagnostics['candidates'] = [{'supplier_id': sid, 'status': record['profile_status'],
                    'missing_fields': record['missing_fields']} for sid, record in self._catalog.records.items()]
            return self._catalog

    def _rows(self, table: str, **params: object) -> list[dict]:
        request = Request(
            f"{self.url}/rest/v1/{table}?{urlencode(params)}",
            headers={"apikey": self.secret_key, "Accept": "application/json"},
        )
        with urlopen(request, timeout=10) as response:
            rows = json.load(response)
        if not isinstance(rows, list):
            raise ValueError("Supabase returned a non-list response")
        return rows

    def _supplier_index(self) -> dict[str, list[dict]]:
        with self._index_lock:
            if self._index is None:
                index: dict[str, list[dict]] = defaultdict(list)
                offset = 0
                while True:
                    rows = self._rows(
                        "suppliers", select="id,canonical_name,homepage_url",
                        order="id.asc", limit=1000, offset=offset,
                    )
                    for row in rows:
                        index[company_name_key(row["canonical_name"])].append(row)
                    if len(rows) < 1000:
                        break
                    offset += 1000
                self._index = dict(index)
        return self._index

    @staticmethod
    def _corroborated(item: dict, candidate: dict, entry: dict,
                      kb: KnowledgeBase) -> bool:
        pool_text = _compact(entry.get("ai_solution_text") or "")
        if pool_text and any(
            cap.supplier_id == item["supplier_id"]
            and cap.evidence.text
            and _compact(cap.evidence.text) in pool_text
            for cap in kb.detailed_capabilities
        ):
            return True
        workbook_homepage = _host(kb.suppliers[item["supplier_id"]].homepage_url)
        return bool(workbook_homepage and workbook_homepage == _host(candidate.get("homepage_url")))

    def enrich(self, items: list[dict], kb: KnowledgeBase) -> None:
        """Mutate result cards with verified source details."""
        for item in items:
            item["supplier_profile"] = None
            item["profile_status"] = "unavailable"
        if not items or not self.secret_key or urlparse(self.url).scheme != "https":
            return

        try:
            index = self._supplier_index()
            candidates_by_item = {
                item["supplier_id"]: index.get(company_name_key(item["name"]), [])
                for item in items
            }
            ids = sorted({candidate["id"] for candidates in candidates_by_item.values()
                          for candidate in candidates})
            entries: dict[str, list[dict]] = defaultdict(list)
            if ids:
                for row in self._rows(
                    "pool_entries",
                    select="supplier_id,sply_pool_no,specialization,ai_solution_text,raw_record",
                    source_program="eq.AI바우처", source_year="eq.2026",
                    supplier_id="in.(" + ",".join(ids) + ")",
                ):
                    entries[row["supplier_id"]].append(row)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError) as error:
            logging.warning("Supplier profile lookup unavailable: %s", type(error).__name__)
            return

        for item in items:
            candidates = candidates_by_item[item["supplier_id"]]
            if not candidates:
                item["profile_status"] = "not_found"
                continue
            matched = [
                (candidate, entry)
                for candidate in candidates
                for entry in entries.get(candidate["id"], [])
                if self._corroborated(item, candidate, entry, kb)
            ]
            if len(matched) != 1:
                item["profile_status"] = "ambiguous" if len(matched) > 1 else "needs_review"
                continue
            candidate, entry = matched[0]
            raw = entry.get("raw_record") or {}
            item["supplier_profile"] = {
                "specialization": _text(entry.get("specialization")),
                "ai_solution_description": _text(entry.get("ai_solution_text")),
                "address": _text(raw.get("splyCmpAddr")),
                "phone": _text(raw.get("bizTelNo")),
                "representative": _text(raw.get("splyCmpRpstNm")),
                "homepage_url": _text(candidate.get("homepage_url")),
                "source_pool_no": entry["sply_pool_no"],
            }
            item["profile_status"] = "matched"

    def available_profiles(self, kb: KnowledgeBase, *, diagnostics: dict | None = None) -> dict[str, dict]:
        """Return detailed suppliers whose five source fields can all be shown."""
        ids = sorted({cap.supplier_id for cap in kb.detailed_capabilities})
        items = [{"supplier_id": sid, "name": kb.suppliers[sid].name} for sid in ids]
        self.enrich(items, kb)
        if diagnostics is not None:
            diagnostics["candidates"] = [{
                "supplier_id": item["supplier_id"], "status": item["profile_status"],
                "missing_fields": [field for field in REQUIRED_PROFILE_FIELDS
                                   if not (item["supplier_profile"] or {}).get(field)],
            } for item in items]
        if any(item["profile_status"] == "unavailable" for item in items):
            raise RuntimeError("Supabase 공급기업 상세정보를 조회할 수 없습니다.")
        return {
            item["supplier_id"]: item["supplier_profile"]
            for item in items
            if item["profile_status"] == "matched"
            and all(item["supplier_profile"].get(field) for field in REQUIRED_PROFILE_FIELDS)
        }
