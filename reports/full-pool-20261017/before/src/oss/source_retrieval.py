"""Bounded lexical retrieval over verified supplier descriptions, not fit grading."""

from collections import Counter
import math
import re


def _terms(text: str) -> Counter:
    text = re.sub(r"[^a-z0-9가-힣]", "", text.casefold())
    return Counter(text[start:start + size] for size in (2, 3)
                   for start in range(len(text) - size + 1))


class SupplierSourceIndex:
    def __init__(self, descriptions: dict[str, str]):
        self.documents = {sid: _terms(text[:30000]) for sid, text in descriptions.items() if text.strip()}
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
        return [sid for _, sid in sorted(scores, key=lambda row: (-row[0], row[1]))]

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
