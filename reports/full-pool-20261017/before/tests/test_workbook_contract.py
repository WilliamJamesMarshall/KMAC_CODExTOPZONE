import os
import unittest

from oss.workbook import load_knowledge_base


@unittest.skipUnless(os.environ.get("OSS_WORKBOOK_PATH"), "Set OSS_WORKBOOK_PATH to run the source contract check")
class WorkbookContractTests(unittest.TestCase):
    def test_v03_source_relationships_are_preserved(self) -> None:
        kb = load_knowledge_base(os.environ["OSS_WORKBOOK_PATH"])
        self.assertEqual(len(kb.tasks), 147)
        self.assertEqual(len(kb.solutions), 169)
        self.assertEqual(kb.audit["sheet_rows"]["활동연결"], 274)
        self.assertEqual(len(kb.detailed_capabilities), 271)
        self.assertEqual({item["task_id"] for item in kb.audit["excluded_links"]}, {"J005", "J007"})
        self.assertEqual(kb.audit["broken_source_refs"], [])
        self.assertTrue(all(task.review_status == "미검토" for task in kb.tasks.values()))


if __name__ == "__main__":
    unittest.main()
