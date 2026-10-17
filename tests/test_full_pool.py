"""Full DB identity, bounded retrieval/review, and the two-supplier contract."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from oss.presentation import build_front_result
from oss.models import WebPage
from oss.source_retrieval import SupplierSourceIndex
from oss.supplier_catalog import build_catalog
from oss.supplier_profile import SupplierProfileClient
from oss.supplier_advice import add_supplier_advice, _repair_reference
from oss.pdf_report import build_report
from test_logic import test_kb
from test_supplier_advice import SOURCE, card, result
from test_pdf_report import report_fixture
from test_empty_output import complete_result
from oss.empty_output import missing_output_fields


def db_rows(sid='db-new', name='신규 공급기업', number=7000):
    supplier = {'id': sid, 'canonical_name': name, 'homepage_url': 'https://new.example/'}
    entry = {'supplier_id': sid, 'sply_pool_no': number, 'specialization': '공정 분석',
             'ai_solution_text': SOURCE + ' 공정 품질예측 기능',
             'raw_record': {'splyPoolNo': number, 'splyCmpNm': name, 'splyCmpAddr': '서울',
                            'bizTelNo': '02-123-4567', 'splyCmpRpstNm': '담당자'}}
    return supplier, entry


class CatalogTests(unittest.TestCase):
    def test_supplier_without_workbook_row_is_retrieved_by_canonical_id(self):
        kb = test_kb()
        supplier, entry = db_rows()
        catalog = build_catalog([supplier], [entry], kb)
        work = {'task_id': 'J014', 'solution_name': '공정 품질예측', 'mechanism': '공정 분석',
                'inputs': ['생산 기록'], 'outputs': ['품질 관련 요인'], 'mapping_reason': '공정 분석',
                'business_evidence': [{'url': 'https://buyer.example', 'quote': '생산', 'fact_id': 'B1'}]}
        data = build_front_result([WebPage('https://buyer.example', '기업', '')], kb,
            {'fields': {}, 'profile': {}, 'quality': {}}, {'opportunities': [work], 'quality': {}},
            candidate_limit=24, supplier_catalog=catalog, eligible_supplier_ids=set(catalog.profiles))
        self.assertEqual(data['suppliers_by_task']['J014'], ['db-new'])
        self.assertEqual(data['suppliers'][0]['profile_status'], 'matched')
        self.assertNotIn('task_advice', data['suppliers'][0])  # Retrieval alone never certifies fit.
        self.assertEqual(data['analysis_meta']['max_suppliers_per_work'], 2)

    def test_identity_mismatch_duplicate_entry_and_missing_homepage_are_withheld(self):
        for defect in ('name', 'pool', 'duplicate', 'homepage'):
            supplier, entry = db_rows()
            entries = [entry]
            if defect == 'name': entry['raw_record']['splyCmpNm'] = '다른 기업'
            if defect == 'pool': entry['raw_record']['splyPoolNo'] = 123
            if defect == 'duplicate': entries.append(deepcopy(entry))
            if defect == 'homepage': supplier['homepage_url'] = '미기재'
            with self.subTest(defect=defect):
                catalog = build_catalog([supplier], entries, test_kb())
                self.assertEqual(len(catalog.records), 1)
                self.assertEqual(catalog.profiles, {})

    def test_legacy_alias_requires_corroboration_not_only_company_name(self):
        supplier, entry = db_rows(name='(주)예시AI')
        kb = test_kb()
        self.assertEqual(build_catalog([supplier], [entry], kb).aliases['F001'], 'db-new')
        entry['ai_solution_text'] = '원문 근거가 전혀 다른 서비스입니다.'
        self.assertNotIn('F001', build_catalog([supplier], [entry], kb).aliases)

    def test_paging_reads_beyond_first_thousand_and_detects_repeated_page(self):
        client = SupplierProfileClient('https://db.example', 'server-key')
        page = [{'id': str(i)} for i in range(1000)]
        with patch.object(client, '_rows', side_effect=[page, [{'id': '1000'}]]) as read:
            self.assertEqual(len(client._all_rows('suppliers')), 1001)
            self.assertEqual([c.kwargs['offset'] for c in read.call_args_list], [0, 1000])
        with patch.object(client, '_rows', return_value=page), self.assertRaises(ValueError):
            client._all_rows('suppliers')

    def test_failed_refresh_never_replaces_good_catalog_with_partial_data(self):
        client = SupplierProfileClient('https://db.example', 'server-key')
        supplier, entry = db_rows()
        with patch.object(client, '_all_rows', side_effect=[[supplier], [entry]]):
            original = client.catalog(test_kb())
        client._catalog_time = -10000
        with patch.object(client, '_all_rows', side_effect=[[supplier], OSError('connection lost')]), \
                self.assertRaises(RuntimeError):
            client.catalog(test_kb())
        self.assertIs(client._catalog, original)

    def test_domain_route_uses_exact_rare_words_not_similar_character_fragments(self):
        descriptions = {'correct': '센서 예측 솔루션. 양식장 수조의 생장 데이터를 분석합니다.',
                        'noisy': '관광 기록을 관측하고 행사장 운영관리 및 생산 기록을 분석합니다.'}
        descriptions.update({f'generic{i}': '기록 관리 솔루션으로 생산 기록을 관리합니다.' for i in range(20)})
        index = SupplierSourceIndex(descriptions, split_solutions=True)
        query = index.domain_query({'target_function': '양식장 생장', 'inputs': ['관측 기록']})
        self.assertNotIn('기록', query.split())
        self.assertEqual(index.domain_rank(query)[0], 'correct')


def review_fixture(count):
    data = result()
    data['opportunities'] = data['opportunities'][:1]
    data['opportunities'][0]['outputs'] = ['품질 관련 요인과 비교 결과']
    base = data['suppliers'][0]
    data['suppliers'] = [{**deepcopy(base), 'supplier_id': f'S{i:02}'} for i in range(count)]
    data['suppliers_by_task'] = {'J014': [s['supplier_id'] for s in data['suppliers']]}
    return data


class ReviewPolicyTests(unittest.TestCase):
    def fake_ask(self, supported, full=()):
        self.reviewed = []
        def ask(_client, _model, _instructions, payload, _schema, name, **_kwargs):
            if name == 'supplier_task_advice':
                self.reviewed.extend(p['supplier_id'] for p in payload['pairs'])
                cards = [{**card(), 'supplier_id': p['supplier_id'], 'supported_output_id': 'O0',
                          'supported_component': '품질 관련 요인'} for p in payload['pairs'] if p['supplier_id'] in supported]
                return {'cards': cards, 'dispositions': [
                    {'task_id': 'J014', 'supplier_id': p['supplier_id'], 'disposition': 'unsupported',
                     'reason': '실제 기능 근거 없음'} for p in payload['pairs'] if p['supplier_id'] not in supported]}
            return {'checks': [{'task_id': 'J014', 'supplier_id': c['supplier_id'],
                **dict.fromkeys(('supplier_supported', 'demand_fit', 'honest', 'safe_scope', 'capability_fit',
                                 'intrinsic_domain_fit', 'workflow_scope_supported', 'conditions_explicit',
                                 'outputs_aligned', 'component_aligned'), True),
                'coverage_level': 'full' if c['supplier_id'] in full else 'partial',
                'uncovered_requirements': [] if c['supplier_id'] in full else ['비교 결과는 별도 확인'],
                'issues': []} for c in payload['cards']]}
        return ask

    def test_later_full_matches_beat_first_partial_matches_after_all_twelve_reviewed(self):
        data = review_fixture(24)
        with patch('oss.supplier_advice._ask', side_effect=self.fake_ask({f'S{i:02}' for i in range(12)}, {'S10', 'S11'})):
            add_supplier_advice(data, client=object())
        self.assertEqual(len(self.reviewed), 12)
        self.assertEqual(data['suppliers_by_task']['J014'], ['S10', 'S11'])

    def test_zero_match_review_is_bounded_at_twenty_four_and_reported(self):
        data, diagnostics = review_fixture(30), {}
        with patch('oss.supplier_advice._ask', side_effect=self.fake_ask(set())):
            add_supplier_advice(data, client=object(), diagnostics=diagnostics, repair_attempts=1)
        self.assertEqual(len(self.reviewed), 24)
        self.assertEqual(diagnostics['review_limit_reached_tasks'], ['J014'])
        self.assertEqual(data['suppliers_by_task']['J014'], [])

    def test_one_qualified_supplier_is_not_filled_with_unsupported_second(self):
        data = review_fixture(24)
        with patch('oss.supplier_advice._ask', side_effect=self.fake_ask({'S02'})):
            add_supplier_advice(data, client=object())
        self.assertEqual(data['suppliers_by_task']['J014'], ['S02'])
        self.assertIn('미확인 기능', data['suppliers'][0]['task_advice']['J014']['coverage_note'])

    def test_output_repair_can_only_select_an_existing_original_output(self):
        pair = {'supplier_source': SOURCE, 'source_spans': [{'id': 'S001', 'text': SOURCE}],
                'demand': {'outputs': ['품질 비교', '관리 방향']}}
        check = {'repairable_within_scope': True, 'intrinsic_domain_fit': True,
                 'repair_solution_name': 'A²LAB', 'repair_source_span_id': 'S001', 'repair_output_id': 'O1'}
        self.assertEqual(_repair_reference(check, pair)['supported_output_id'], 'O1')
        self.assertIsNone(_repair_reference({**check, 'repair_output_id': 'O2'}, pair))
        self.assertIsNone(_repair_reference({**check, 'intrinsic_domain_fit': False}, pair))

    def test_pdf_accepts_two_but_rejects_three_in_one_work(self):
        data = report_fixture()
        data['works'][0]['suppliers'] *= 2
        self.assertTrue(build_report(data)[0].startswith(b'%PDF'))
        data['works'][0]['suppliers'].append(deepcopy(data['works'][0]['suppliers'][0]))
        with self.assertRaisesRegex(ValueError, '2'):
            build_report(data)

    def test_empty_output_checker_flags_three_suppliers_even_if_every_card_is_filled(self):
        data = complete_result()
        base = data['suppliers'][0]
        data['suppliers'] = [{**deepcopy(base), 'supplier_id': f'S{i}'} for i in range(3)]
        data['suppliers_by_task'] = {'J014': ['S0', 'S1', 'S2']}
        self.assertEqual([f['reason'] for f in missing_output_fields(data)], ['supplier_limit_exceeded'])
