import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agents.agent_orchestrator import AgentOrchestrator, AgentType, Request
from agents.education_store import EducationStore
from core.intent_recognizer import IntentCategory
from core.policy_evidence import POLICY_FILE
from core.transfer_requirements import extract_updates
from test_agent_orchestrator import FakeClient


class TransferReasoningTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.policy_path = self.root / 'policies.json'
        self.policy_path.write_bytes(POLICY_FILE.read_bytes())
        self.store = EducationStore(self.root / 'db.sqlite3', self.policy_path)
        with patch('agents.agent_orchestrator.AsyncOpenAI', return_value=FakeClient()), patch('core.intent_recognizer.AsyncOpenAI', return_value=FakeClient()):
            self.orchestrator = AgentOrchestrator('test', education_store=self.store)

    def update(self, message, conv='c'):
        return self.store.update_requirements('student_demo', conv, message)

    def advice(self):
        return self.store.advise_transfer('student_demo', 'c')

    def chat(self, message):
        return asyncio.run(self.orchestrator.run(Request(message, 'student_demo', 'c', intent=IntentCategory.OTHER)))

    def rewrite_policy(self, edit):
        policies = json.loads(self.policy_path.read_text(encoding='utf-8'))
        edit(policies)
        self.policy_path.write_text(json.dumps(policies, ensure_ascii=False), encoding='utf-8')

    def test_multiturn_constraints_no_silent_relaxation(self):
        self.update('帮我转到周日班，不想补钱')
        self.assertEqual([r['id'] for r in self.advice()['candidates']], ['PY-SUN-PM'])
        self.update('下午不行，只能晚上')
        result = self.advice()
        self.assertEqual(result['candidates'], [])
        self.assertEqual(result['alternatives'][0]['requires_relaxation'], 'max_fee_cents')
        self.assertEqual(self.store.requirements('student_demo', 'c')['slots']['max_fee_cents'], 0)
        self.update('最多补两百元也可以')
        result = self.advice()
        self.assertEqual([r['id'] for r in result['candidates']], ['PY-SUN-EVE'])
        self.assertEqual(result['requirements']['slots']['periods'], ['晚上'])

    def test_hard_and_soft_teacher_preference(self):
        self.update('周日，老师最好不变')
        self.assertEqual([r['id'] for r in self.advice()['candidates']], ['PY-SUN-EVE', 'PY-SUN-PM'])
        self.update('不想补钱')
        self.assertEqual([r['id'] for r in self.advice()['candidates']], ['PY-SUN-PM'])
        self.update('老师不能变')
        self.assertFalse(self.advice()['candidates'])

    def test_clear_and_ambiguous_requirements(self):
        self.update('只能周日晚上，不想补钱')
        state = self.update('不想补钱，但最多补两百元')
        self.assertEqual(state['slots']['max_fee_cents'], 0)
        self.assertTrue(state['ambiguities'])
        self.assertEqual(self.advice()['status'], 'needs_clarification')
        self.update('最多补200元')
        self.assertEqual(self.advice()['status'], 'matched')
        state = self.update('时间不限，费用不限，老师不限')
        self.assertEqual(state['slots'], {})

    def test_requirements_persist_and_do_not_cross_conversations(self):
        state = self.update('只能周日晚上，最多补200元')
        restored = EducationStore(self.root / 'db.sqlite3', self.policy_path)
        self.assertEqual(restored.requirements('student_demo', 'c'), state)
        self.assertEqual(restored.requirements('student_demo', 'another')['slots'], {})
        self.assertEqual(restored.requirements('someone_else', 'c')['slots'], {})
        self.assertEqual(state['events'][-1]['message'], '只能周日晚上，最多补200元')

    def test_clarification_uses_candidate_differences(self):
        result = self.advice()
        self.assertIn('时段', result['question'])
        self.assertIn('下午', result['question'])
        self.assertIn('晚上', result['question'])

    def test_free_assessment_unknown_then_true_or_false(self):
        unknown = self.store.assess_free_transfer('student_demo', 'c')
        self.assertEqual(unknown['status'], 'unknown')
        self.assertIn('target.price_cents', unknown['missing_fields'])
        self.assertEqual(unknown['facts']['source.paid_cents']['value'], 200000)
        positive = self.store.assess_free_transfer('student_demo', 'c', 'PY-SUN-PM')
        negative = self.store.assess_free_transfer('student_demo', 'c', 'PY-SUN-EVE')
        self.assertEqual(positive['status'], 'eligible')
        self.assertEqual(negative['status'], 'ineligible')
        failed = [r for r in negative['checks'] if r['status'] == 'fail']
        self.assertEqual([r['clause_id'] for r in failed], ['F5'])
        self.assertEqual(failed[0]['citation'], 'demo-free-transfer-v2#F5')
        self.assertEqual(failed[0]['left'], 220000)

    def test_policy_changes_determine_which_facts_are_queried(self):
        before = self.store.assess_free_transfer('student_demo', 'c', 'PY-SUN-PM')
        self.assertNotIn('source.remaining', before['facts'])
        self.rewrite_policy(lambda ps: ps[1]['clauses'].append({
            'id': 'F6', 'text': '本测试政策要求剩余课时至少20节', 'left': 'source.remaining', 'op': 'gte', 'value': 20}))
        after = self.store.assess_free_transfer('student_demo', 'c', 'PY-SUN-PM')
        self.assertEqual(after['facts']['source.remaining']['value'], 12)
        self.assertEqual(after['status'], 'ineligible')
        self.assertIn('source.remaining', [q['field'] for q in after['query_plan']])

    def test_policy_conflict_expiry_and_unsupported_field_fail_closed(self):
        original = self.policy_path.read_bytes()
        self.rewrite_policy(lambda ps: ps.append(dict(ps[1], id='conflicting-policy')))
        self.assertEqual(self.store.assess_free_transfer('student_demo', 'c', 'PY-SUN-PM')['status'], 'unknown')
        self.policy_path.write_bytes(original)
        self.rewrite_policy(lambda ps: ps[1].update(effective_to='2020-01-02'))
        self.assertEqual(self.store.assess_free_transfer('student_demo', 'c', 'PY-SUN-PM')['status'], 'unknown')
        self.policy_path.write_bytes(original)
        self.rewrite_policy(lambda ps: ps[1]['clauses'][0].update(left='source.password; DROP TABLE enrollments'))
        self.assertEqual(self.store.assess_free_transfer('student_demo', 'c', 'PY-SUN-PM')['status'], 'unknown')
        self.assertIsNotNone(self.store.enrollment('student_demo')['enrollment'])

    def test_constraints_enforced_on_draft_and_confirmation(self):
        self.update('只能周日晚上，不想补钱')
        self.assertFalse(self.store.prepare('student_demo', 'c', 'PY-SUN-EVE', '工作')['success'])
        self.update('最多补200元')
        draft = self.store.prepare('student_demo', 'c', 'PY-SUN-EVE', '工作')
        self.assertTrue(draft['success'])
        self.update('不想补钱')
        self.assertFalse(self.store.submit('student_demo', 'c', draft['draft_id'])['success'])

    def test_policy_change_invalidates_confirmation_even_if_price_unchanged(self):
        draft = self.store.prepare('student_demo', 'c', 'PY-SUN-PM', '工作')
        self.rewrite_policy(lambda ps: ps[0].update(version='3'))
        self.assertFalse(self.store.submit('student_demo', 'c', draft['draft_id'])['success'])

    def test_chat_free_assessment_retains_target_question_context(self):
        first = self.chat('我是否符合免费转班条件？')
        self.assertIn('暂时无法确认', first.response)
        self.assertEqual(first.agent_type, AgentType.FEES_ENTITLEMENTS)
        second = self.chat('PY-SUN-PM')
        self.assertIn('满足演示免费转班条件', second.response)
        self.assertEqual(second.tools_used, ['assess_free_transfer'])
        self.assertEqual(self.store.applications('student_demo')['applications'], [])
        self.assertIsNone(self.store.latest_draft('student_demo', 'c'))

    def test_chat_multiturn_advice_and_audit_evidence(self):
        self.chat('帮我转到周日班，不想补钱')
        second = self.chat('下午不行，只能晚上')
        self.assertIn('没有完全匹配', second.response)
        third = self.chat('最多补两百元')
        self.assertIn('PY-SUN-EVE', third.response)
        self.assertIn('200.00', third.response)
        trace = self.orchestrator.get_tool_trace(third.request_id)
        self.assertTrue(trace['tool_calls'][0]['evidence']['candidates'])

    def test_policy_question_does_not_change_constraints(self):
        self.chat('帮我转到周日班，不想补钱')
        before = self.store.requirements('student_demo', 'c')
        self.chat('周六转班政策是什么？')
        self.assertEqual(self.store.requirements('student_demo', 'c'), before)

    def test_correction_within_one_turn(self):
        state = self.update('不是周日，是周六，上午改成晚上')
        self.assertEqual(state['slots']['days'], ['周六'])
        self.assertEqual(state['slots']['excluded_days'], ['周日'])
        self.assertEqual(state['slots']['periods'], ['晚上'])


if __name__ == '__main__':
    unittest.main()
