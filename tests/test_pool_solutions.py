import unittest

from oss.pool_solutions import named_solutions


class PoolSolutionTests(unittest.TestCase):
    def test_only_explicitly_named_solutions_are_extracted(self) -> None:
        text = (
            "솔루션명: Apollo-S\n실시간 음성 인식과 음성 합성을 지원합니다.\n"
            "솔루션명2: Apollo-R\n사내 문서 검색과 답변을 제공합니다."
        )
        self.assertEqual([name for name, _ in named_solutions(text)], ["Apollo-S", "Apollo-R"])
        self.assertEqual(named_solutions("AI 솔루션을 제공합니다. 고객별 기능을 개발합니다."), [])


if __name__ == "__main__":
    unittest.main()
