"""Build a source-linked supplier catalogue from complete annual DB records."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from urllib.parse import urlparse

from .identity import company_name_key
from .supplier_profile import REQUIRED_PROFILE_FIELDS, SupplierProfileClient, _text


def public_homepage(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip() or any(c.isspace() for c in value.strip()):
        return None
    value = value.strip()
    if '://' not in value:
        value = 'https://' + value
    try:
        parsed = urlparse(value)
        if (parsed.scheme in {'http', 'https'} and parsed.hostname and '.' in parsed.hostname
                and not parsed.username and not parsed.password and parsed.port in {None, 80, 443}):
            return value
    except ValueError:
        pass
    return None


@dataclass
class SupplierCatalog:
    records: dict[str, dict]
    aliases: dict[str, str]
    captured_at: str
    fingerprint: str

    @property
    def profiles(self) -> dict[str, dict]:
        return {sid: item['supplier_profile'] for sid, item in self.records.items()
                if item['profile_status'] == 'matched' and not item['missing_fields']}

    def summary(self) -> dict:
        return {'registered_count': len(self.records), 'recommendable_count': len(self.profiles),
                'legacy_alias_count': len(self.aliases), 'captured_at': self.captured_at,
                'fingerprint': self.fingerprint}


def build_catalog(suppliers: list[dict], entries: list[dict], kb) -> SupplierCatalog:
    registry = {item['id']: item for item in suppliers}
    if len(registry) != len(suppliers):
        raise ValueError('Duplicate supplier IDs in registry pagination')
    grouped = defaultdict(list)
    for entry in entries:
        if entry['supplier_id'] not in registry:
            raise ValueError('Pool entry has no registered supplier')
        grouped[entry['supplier_id']].append(entry)
    records, aliases = {}, {}
    name_index = defaultdict(list)
    for sid, supplier in kb.suppliers.items():
        name_index[company_name_key(supplier.name)].append(sid)
    for sid, source_rows in grouped.items():
        supplier = registry[sid]
        entry = source_rows[0]
        raw = entry.get('raw_record') or {}
        status = 'matched'
        if len(source_rows) != 1:
            status = 'ambiguous'
        elif (str(raw.get('splyPoolNo', '')).strip() != str(entry['sply_pool_no']).strip()
                or company_name_key(raw.get('splyCmpNm') or '') != company_name_key(supplier['canonical_name'])):
            status = 'needs_review'
        profile = {'specialization': _text(entry.get('specialization')),
            'ai_solution_description': _text(entry.get('ai_solution_text')),
            'address': _text(raw.get('splyCmpAddr')), 'phone': _text(raw.get('bizTelNo')),
            'representative': _text(raw.get('splyCmpRpstNm')),
            'homepage_url': public_homepage(supplier.get('homepage_url')) or public_homepage(raw.get('splyCmpHmpg')),
            'source_pool_no': entry['sply_pool_no'], 'source_program': 'AI바우처', 'source_year': 2026,
            'source_hash': hashlib.sha256((entry.get('ai_solution_text') or '').encode()).hexdigest()}
        for old_id in name_index[company_name_key(supplier['canonical_name'])]:
            item = {'supplier_id': old_id}
            if status == 'matched' and SupplierProfileClient._corroborated(item, supplier, entry, kb):
                # Ambiguous legacy names never merge two registered entities.
                aliases[old_id] = sid if old_id not in aliases else None
                if not profile['homepage_url']:
                    profile['homepage_url'] = public_homepage(kb.suppliers[old_id].homepage_url)
        missing = [field for field in (*REQUIRED_PROFILE_FIELDS, 'homepage_url')
                   if not profile.get(field) or str(profile[field]).strip().casefold() in
                   {'없음', '정보없음', '미제공', '미기재', 'none', 'null', 'n/a', '-'}]
        records[sid] = {'supplier_id': sid, 'name': supplier['canonical_name'].strip(),
            'homepage_url': profile['homepage_url'], 'supplier_profile': profile,
            'profile_status': status, 'missing_fields': missing}
    aliases = {old: sid for old, sid in aliases.items() if sid is not None}
    payload = json.dumps({'records': records, 'aliases': aliases}, ensure_ascii=False, sort_keys=True)
    return SupplierCatalog(records, aliases, datetime.now(timezone.utc).isoformat(),
                           hashlib.sha256(payload.encode()).hexdigest())
