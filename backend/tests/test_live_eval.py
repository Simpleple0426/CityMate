import unittest
from evaluation.live_cases import CASES
from evaluation.live_eval import check_turn


class LiveEvaluationTests(unittest.TestCase):
    def test_colloquial_zero_budget_survives_time_correction(self):
        from core.transfer_requirements import extract_updates, apply_updates
        parsed = extract_updates('我周六上不了课了，想换到周日，不想再掏钱')
        slots = apply_updates({}, parsed)
        self.assertEqual(slots['max_fee_cents'], 0)
        slots = apply_updates({'slots': slots}, extract_updates('只能晚上'))
        self.assertEqual(slots['max_fee_cents'], 0)
    def test_suite_has_unique_cases_and_defined_confirmation_dependencies(self):
        self.assertEqual(len(CASES), 30)
        self.assertEqual(len({case['id'] for case in CASES}), len(CASES))
        for case in CASES:
            draft_seen = False
            for step in case['turns']:
                if step['message'] in ('{confirm}', '{first_confirm}'):
                    self.assertTrue(draft_seen, case['id'])
                draft_seen |= 'draft' in step['expected']

    def test_reply_alone_cannot_pass_submission_check(self):
        snapshot = {'requirements': {'slots': {}}, 'applications': [], 'draft': None}
        checks = check_turn({'applications': 1}, snapshot, {'response': '已提交'}, [])
        self.assertFalse(all(c['passed'] for c in checks))

    def test_assessment_requires_trace_evidence(self):
        checks = check_turn({'assessment': 'eligible'}, {}, {'response': '符合'}, [])
        self.assertFalse(all(c['passed'] for c in checks))
