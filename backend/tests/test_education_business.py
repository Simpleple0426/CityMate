import asyncio
from enum import Enum
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, AsyncMock

from agents.agent_orchestrator import AgentOrchestrator, AgentType, AgentResponse, Request
from agents.education_store import EducationStore
from agents.education_tools import education_tools
from core.intent_recognizer import IntentCategory
from test_agent_orchestrator import FakeClient


class BusinessTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "business.sqlite3"
        self.store = EducationStore(self.path)
        with patch('agents.agent_orchestrator.AsyncOpenAI', return_value=FakeClient()), patch('core.intent_recognizer.AsyncOpenAI', return_value=FakeClient()):
            self.orchestrator = AgentOrchestrator('test', education_store=self.store)

    def request(self, message, **kwargs):
        return Request(message, 'student_demo', 'conversation-1', intent=kwargs.pop('intent', IntentCategory.OTHER), **kwargs)

    def test_actual_role_pool_and_permissions(self):
        self.assertEqual(set(self.orchestrator._pool), {
            AgentType.COURSE_CONSULTATION, AgentType.COURSE_PLANNING,
            AgentType.ACADEMIC_SERVICE, AgentType.FEES_ENTITLEMENTS, AgentType.ESCALATION})
        for role in ('course_consultation', 'course_planning', 'academic_service', 'fees_entitlements'):
            tools = education_tools(self.store, role)
            self.assertNotIn('submit_transfer', tools)
            self.assertEqual('prepare_transfer' in tools, role == 'academic_service')
            for spec in tools.values():
                self.assertNotIn('user_id', spec.input_schema['properties'])

    def test_catalog_identity_and_rule_checks(self):
        self.assertIsNone(self.store.enrollment('another-user')['enrollment'])
        classes = self.store.catalog(day='周日', foundation=0)['classes']
        self.assertTrue(classes)
        self.assertTrue(all(c['course'] == 'python' for c in classes))
        self.assertFalse(self.store.quote('student_demo', 'PY-SUN-AM')['eligible'])
        self.assertFalse(self.store.quote('student_demo', 'DA-SUN-PM')['eligible'])
        self.assertFalse(self.store.quote('another-user', 'PY-SUN-PM')['eligible'])
        self.assertEqual(self.store.quote('student_demo', 'PY-SUN-EVE')['fee_cents'], 20000)

    def test_confirmation_and_persistence_are_independent_of_llm(self):
        draft = self.store.prepare('student_demo', 'conversation-1', 'PY-SUN-PM', '工作调整')
        self.assertEqual(self.store.applications('student_demo')['applications'], [])
        ambiguous = asyncio.run(self.orchestrator.run(self.request('可以')))
        self.assertIn(draft['draft_id'], ambiguous.response)
        self.assertEqual(self.store.applications('student_demo')['applications'], [])
        self.orchestrator.education_store = EducationStore(self.path)
        result = asyncio.run(self.orchestrator.run(self.request(draft['confirmation'])))
        self.assertIn('待教务审核', result.response)
        self.assertEqual(result.tools_used, ['submit_transfer'])
        asyncio.run(self.orchestrator.run(self.request(draft['confirmation'])))
        self.assertEqual(len(self.store.applications('student_demo')['applications']), 1)
        self.assertEqual(self.store.enrollment('student_demo')['enrollment']['class_id'], 'PY-SAT-AM')

    def test_cross_user_and_conversation_confirmation_rejected(self):
        draft = self.store.prepare('student_demo', 'conversation-1', 'PY-SUN-PM', '工作')
        self.assertFalse(self.store.submit('another-user', 'conversation-1', draft['draft_id'])['success'])
        self.assertFalse(self.store.submit('student_demo', 'another-conversation', draft['draft_id'])['success'])

    def test_changed_draft_cancelled_draft_and_stale_quote_rejected(self):
        first = self.store.prepare('student_demo', 'conversation-1', 'PY-SUN-PM', '工作')
        second = self.store.prepare('student_demo', 'conversation-1', 'PY-SUN-EVE', '改时间')
        self.assertFalse(self.store.submit('student_demo', 'conversation-1', first['draft_id'])['success'])
        with self.store.connection() as db:
            db.execute("UPDATE classes SET price_cents=230000 WHERE id='PY-SUN-EVE'")
        self.assertFalse(self.store.submit('student_demo', 'conversation-1', second['draft_id'])['success'])
        third = self.store.prepare('student_demo', 'conversation-1', 'PY-SUN-PM', '工作')
        self.store.cancel('student_demo', 'conversation-1')
        self.assertFalse(self.store.submit('student_demo', 'conversation-1', third['draft_id'])['success'])

    def test_concurrent_confirmations_create_one_application(self):
        draft = self.store.prepare('student_demo', 'conversation-1', 'PY-SUN-PM', '工作')
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.store.submit('student_demo', 'conversation-1', draft['draft_id']), range(4)))
        self.assertTrue(all(r['success'] for r in results))
        self.assertEqual(len({r['application']['id'] for r in results}), 1)

    def test_contextual_routing_and_topic_switch(self):
        self.store.activate('student_demo', 'conversation-1')
        for message in ('下午的', '改成晚上', 'PY-SUN-PM'):
            self.assertEqual(self.orchestrator._route_decision(self.request(message)).primary_agent, AgentType.ACADEMIC_SERVICE)
        for message, role in [('转班有什么规定', AgentType.COURSE_CONSULTATION),
                              ('我还剩几节课', AgentType.FEES_ENTITLEMENTS),
                              ('推荐零基础课程', AgentType.COURSE_PLANNING),
                              ('转人工', AgentType.ESCALATION)]:
            self.assertEqual(self.orchestrator._route_decision(self.request(message)).primary_agent, role)
        other = Request('下午的', 'student_demo', 'other', intent=IntentCategory.OTHER)
        self.assertNotEqual(self.orchestrator._route_decision(other).primary_agent, AgentType.ACADEMIC_SERVICE)

    def test_collaboration_passes_results_to_owner_in_order(self):
        req = self.request('帮我转到周日班，不要额外花钱')
        decision = self.orchestrator._route_decision(req)
        calls = []
        async def execute(request, agent_type):
            calls.append((agent_type, request.context))
            return AgentResponse(agent_type, agent_type.value + ' evidence', True)
        self.orchestrator._execute = execute
        result = asyncio.run(self.orchestrator.run(req))
        self.assertEqual([a for a, _ in calls], [AgentType.COURSE_PLANNING, AgentType.FEES_ENTITLEMENTS, AgentType.ACADEMIC_SERVICE])
        self.assertIn('course_planning evidence', calls[-1][1])
        self.assertIn('fees_entitlements evidence', calls[-1][1])
        self.assertEqual(result.response, 'academic_service evidence')
        self.assertEqual(result.primary_agent, decision.primary_agent)

    def test_tool_round_trip_creates_reviewable_draft_not_application(self):
        call = SimpleNamespace(id='draft-call', function=SimpleNamespace(name='prepare_transfer', arguments='{"target_id":"PY-SUN-PM","reason":"工作调整"}'))
        responses = [SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='', tool_calls=[call]))]),
                     SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='已完成转班', tool_calls=[]))])]
        class Client:
            def __init__(self):
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
            async def create(self, **kwargs):
                return responses.pop(0)
        self.orchestrator._pool[AgentType.ACADEMIC_SERVICE][0]._client = Client()
        result = asyncio.run(self.orchestrator.run(self.request('帮我转到PY-SUN-PM')))
        self.assertIn('尚未提交', result.response)
        self.assertIn('确认提交 ', result.response)
        self.assertNotIn('已完成转班', result.response)
        self.assertEqual(self.store.applications('student_demo')['applications'], [])

    def test_selection_change_invalidates_old_confirmation_even_if_model_fails(self):
        for message in ('改成晚上', '上午的', 'PY-SUN-EVE'):
            with self.subTest(message=message):
                self.store.cancel('student_demo', 'conversation-1')
                draft = self.store.prepare('student_demo', 'conversation-1', 'PY-SUN-PM', '工作')
                asyncio.run(self.orchestrator.run(self.request(message)))
                self.assertFalse(self.store.submit('student_demo', 'conversation-1', draft['draft_id'])['success'])

    def test_capacity_rechecked_at_submission(self):
        draft = self.store.prepare('student_demo', 'conversation-1', 'PY-SUN-PM', '工作')
        with self.store.connection() as db:
            db.execute("UPDATE classes SET seats=0 WHERE id='PY-SUN-PM'")
        self.assertFalse(self.store.submit('student_demo', 'conversation-1', draft['draft_id'])['success'])
        self.assertEqual(self.store.applications('student_demo')['applications'], [])

    def test_http_confirmation_contract(self):
        from fastapi.testclient import TestClient
        from api import main
        draft = self.store.prepare('student_demo', 'conversation-1', 'PY-SUN-PM', '工作')
        memory = SimpleNamespace(
            get_context=AsyncMock(return_value=SimpleNamespace(recent_messages=[], to_prompt_text=lambda: '')),
            add_message=AsyncMock(), update_profile=AsyncMock())
        roles = Enum('MsgRole', {'USER': 'user', 'ASSISTANT': 'assistant'})
        with patch.object(main, '_orchestrator', self.orchestrator), patch.object(main, '_memory', memory), patch.dict('sys.modules', {'memory.conversation_memory': SimpleNamespace(MsgRole=roles)}):
            # No lifespan: real Redis, Chroma and model initialization are deliberately excluded.
            client = TestClient(main.app)
            try:
                response = client.post('/chat', json={'message': draft['confirmation'], 'user_id': 'student_demo', 'conv_id': 'conversation-1'})
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data['agent_type'], 'academic_service')
                self.assertEqual(data['intent'], 'academic_service')
                self.assertEqual(data['tools_used'], ['submit_transfer'])
                self.assertIn('待教务审核', data['response'])
            finally:
                client.close()


if __name__ == '__main__':
    unittest.main()
