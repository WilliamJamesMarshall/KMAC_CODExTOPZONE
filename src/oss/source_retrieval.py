"""Bounded lexical retrieval over verified supplier descriptions, not fit grading."""

from collections import Counter
import math
import re


def _terms(text: str) -> Counter:
    text = re.sub(r"[^a-z0-9가-힣]", "", text.casefold())
    return Counter(text[start:start + size] for size in (2, 3)
                   for start in range(len(text) - size + 1))


class SupplierSourceIndex:
    def __init__(self, descriptions: dict[str, str], *, split_solutions: bool = False):
        self.sources = {sid: text.casefold() for sid, text in descriptions.items() if text.strip()}
        self.documents, self.owners, self.block_texts = {}, {}, {}
        for sid, text in descriptions.items():
            blocks = re.split(r'\n(?=\s*(?:[▣◆■□]|\d+\.\s*|솔루션\s*\d+|○\s*솔루션))', text) if split_solutions else [text]
            for number, block in enumerate(blocks):
                if not block.strip():
                    continue
                key = f'{sid}\x1f{number}'
                self.documents[key] = _terms(block[:30000])
                self.owners[key] = sid
                self.block_texts[key] = block.casefold()
        self.lengths = {sid: sum(terms.values()) for sid, terms in self.documents.items()}
        self.average_length = sum(self.lengths.values()) / max(len(self.lengths), 1) or 1
        self.frequency = Counter(term for terms in self.documents.values() for term in terms)

    def rank(self, text: str) -> list[str]:
        query = set(_terms(text))
        count = len(self.documents)
        scores = []
        for sid, terms in self.documents.items():
            normalizer = 1.2 * (0.25 + 0.75 * self.lengths[sid] / self.average_length)
            score = 0.0
            for term in query & terms.keys():
                frequency = self.frequency[term]
                if count >= 5 and frequency > count * 0.8:
                    continue
                weight = math.log(1 + (count - frequency + 0.5) / (frequency + 0.5))
                score += weight * terms[term] * 2.2 / (terms[term] + normalizer)
            if score > 0:
                scores.append((score, sid))
        ranked, seen = [], set()
        for _, key in sorted(scores, key=lambda row: (-row[0], row[1])):
            sid = self.owners[key]
            if sid not in seen:
                seen.add(sid); ranked.append(sid)
        return ranked

    def domain_query(self, work: dict) -> str:
        """Recover distinctive buyer terms without hard-coded supplier/domain lists."""
        words = re.findall(r'[가-힣A-Za-z][가-힣A-Za-z0-9]{1,}', ' '.join(
            [work.get('target_function', ''), *work.get('inputs', [])]))
        words = [re.sub(r'(?:에서|으로|들의|의|를|을|와|과)$', '', word.casefold()) for word in words]
        ranked = []
        for word in set(words):
            if len(word) < 2:
                continue
            frequency = sum(word in source for source in self.sources.values())
            if 0 < frequency <= max(3, len(self.sources) * 0.08):
                ranked.append((frequency, -len(word), word))
        # Broad words such as 기록 must not drown out an explicit 양식장 match.
        rarest = min((row[0] for row in ranked), default=0)
        distinctive = [word for frequency, _, word in sorted(ranked) if frequency <= rarest * 4]
        return ' '.join(distinctive[:8])

    def domain_rank(self, query: str) -> list[str]:
        """Rank exact distinctive terms within one product, avoiding n-gram noise."""
        words = query.split()
        weights = {word: math.log(1 + len(self.sources) / max(1, sum(
            word in source for source in self.sources.values()))) for word in words}
        scores = {}
        for key, text in self.block_texts.items():
            score = sum(weight for word, weight in weights.items() if word in text)
            sid = self.owners[key]
            if score > 0:
                scores[sid] = max(scores.get(sid, 0), score)
        return sorted(scores, key=lambda sid: (-scores[sid], sid))

    def pool_candidates(self, task, work: dict, legacy_ids: list[str]) -> tuple[list[str], dict]:
        function = ' '.join((task.name, task.business_purpose, task.expected_output, task.activity_tags))
        application = ' '.join([work.get('solution_name', ''), work.get('mechanism', ''),
                                *work.get('inputs', []), *work.get('outputs', [])])
        domain = self.domain_query(work)
        views = {'domain_data': self.domain_rank(domain), 'work_output': self.rank(application),
                 'task_function': self.rank(function), 'legacy_task_link': legacy_ids}
        result, seen = [], set()
        for position in range(max(map(len, views.values()), default=0)):
            for view in views.values():
                if position < len(view) and view[position] not in seen:
                    seen.add(view[position]); result.append(view[position])
        return result, {'domain_query': domain,
                        'route_heads': {name: ids[:12] for name, ids in views.items()}}

    def candidates(self, task, work: dict) -> list[str]:
        function = " ".join((task.name, task.business_purpose, task.expected_output, task.activity_tags))
        application = " ".join([work.get('solution_name', ''), work.get('mechanism', ''),
                                *work.get('inputs', []), *work.get('outputs', [])])
        # Interleave the general function and buyer-specific views so generic
        # capabilities are not hidden by industry/product terminology.
        views = [self.rank(function), self.rank(application)]
        result = []
        seen = set()
        for position in range(max(map(len, views), default=0)):
            for view in views:
                if position < len(view) and view[position] not in seen:
                    seen.add(view[position]); result.append(view[position])
        return result
