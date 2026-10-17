import unittest

from oss.pool_prepare import prepare_records, website_urls


class PoolPrepareTests(unittest.TestCase):
    def test_annotated_multiple_urls_are_kept_separate(self) -> None:
        raw = "https://ksleep.care/app (환자용), https://dreamsleep.ksleep.care/login (포털)"
        self.assertEqual(website_urls(raw), [
            "https://ksleep.care/app",
            "https://dreamsleep.ksleep.care/login",
        ])

    def test_email_is_not_treated_as_homepage(self) -> None:
        self.assertEqual(website_urls("j.choi@qisens-ai.com"), [])
        prepared, audit = prepare_records([{
            "splyPoolNo": 2994, "splyCmpNm": "예시", "splyCmpHmpg": "j.choi@qisens-ai.com",
        }])
        self.assertEqual(prepared[0]["url_status"], "invalid")
        self.assertEqual(audit["url_status"], {"invalid": 1})


if __name__ == "__main__":
    unittest.main()
