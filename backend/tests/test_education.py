import asyncio
import json
import unittest
import tempfile
from agents.education_store import EducationStore
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import test_agent_orchestrator as legacy
from agents.agent_orchestrator import (
    AgentOrchestrator, AgentType, KnowledgeAgent, HomeworkAgent,
    StudyPlanAgent, EducationSupportAgent, Request, build_shared_rag_tools,
)
from agents.tools import suggest_required_fields
from core.intent_recognizer import IntentCategory
from core.skill_loader import SkillManager

ROOT = Path(__file__).resolve().parents[1]


class EducationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        store = EducationStore(Path(folder.name) / "test.sqlite3")
        with patch('agents.agent_orchestrator.AsyncOpenAI', return_value=legacy.FakeClient()), patch('core.intent_recognizer.AsyncOpenAI', return_value=legacy.FakeClient()):
            self.orchestrator = AgentOrchestrator('test-only', base_url='http://localhost:1', education_store=store)

    def test_existing_regressions(self):
        for name in sorted(dir(legacy)):
            if name.startswith('test_'):
                with self.subTest(name=name):
                    getattr(legacy, name)()

    def test_education_patterns_and_routes(self):
        for message, intent, agent in [
            ('转班有什么规定', IntentCategory.COURSE_CONSULTATION, AgentType.COURSE_CONSULTATION),
            ('我只有周末有空，该选什么课程', IntentCategory.COURSE_PLANNING, AgentType.COURSE_PLANNING),
            ('帮我转到周日下午班', IntentCategory.ACADEMIC_SERVICE, AgentType.ACADEMIC_SERVICE),
            ('我还剩几节课', IntentCategory.FEES_ENTITLEMENTS, AgentType.FEES_ENTITLEMENTS),
            ('转人工', IntentCategory.HUMAN_HANDOFF, AgentType.ESCALATION),
        ]:
            with self.subTest(message=message):
                detected = self.orchestrator._intent_recognizer._pattern_recognize(message)
                self.assertEqual(detected['intent'], intent)
                decision = self.orchestrator._route_decision(Request(message, 's', 'c', intent=intent))
                self.assertEqual(decision.primary_agent, agent)

    def test_collaboration_and_clarification(self):
        req = Request('帮我转到周日班，不要额外花钱', 's', 'c', intent=IntentCategory.KNOWLEDGE_QUERY)
        decision = self.orchestrator._route_decision(req)
        self.assertIn(AgentType.COURSE_PLANNING, decision.supporting_agents)
        self.assertIn(AgentType.FEES_ENTITLEMENTS, decision.supporting_agents)
        unclear = Request('这个不会', 's', 'c', intent=IntentCategory.OTHER, intent_confidence=0.1)
        self.assertIn('课程', asyncio.run(self.orchestrator.run(unclear)).response)

    def test_profiles_skills_and_entities(self):
        manager = SkillManager(str(ROOT / 'skills'))
        manager.load()
        self.assertFalse(manager.errors)
        for cls in (KnowledgeAgent, HomeworkAgent, StudyPlanAgent, EducationSupportAgent):
            agent = cls(legacy.FakeClient(), 'test', manager)
            agent.set_shared_tools(build_shared_rag_tools(None))
            self.assertEqual(set(agent.get_tools()), {'search_knowledge_base'})
            self.assertIn('没有题目', agent._build_system_prompt(Request('这个不会', 's', 'c')))
        entities = self.orchestrator._intent_recognizer._extract_entities('我大一，每天一小时学数据结构二叉树')
        self.assertEqual(entities['grade'], ['大一'])
        self.assertIn('数据结构', entities['subject'])
        req = Request('复习计划', 's', 'c', intent=IntentCategory.STUDY_PLAN)
        self.assertIn('每日学习时间', suggest_required_fields(req, {})['required_fields'])
        docs = json.loads((ROOT / 'data/demo_docs/education.json').read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(docs), 5)

    def test_education_agent_injects_task_resources_with_actual_tools(self):
        from agents.agent_orchestrator import AcademicServiceAgent, CourseConsultationAgent
        manager = SkillManager(str(ROOT / 'skills'))
        manager.load()
        for cls, expected in ((AcademicServiceAgent, True), (CourseConsultationAgent, False)):
            agent = cls(legacy.FakeClient(), 'test', manager)
            agent.store = self.orchestrator.education_store
            prompt = agent._build_system_prompt(Request('下午的', 'student_demo', 'c'))
            self.assertEqual('[template: templates/transfer_draft.md]' in prompt, expected)

    def test_education_rag_tool_round_trip(self):
        def completion(content=None, calls=None):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=calls))])
        call = SimpleNamespace(id='rag1', type='function', function=SimpleNamespace(name='search_knowledge_base', arguments='{"query":"二叉树"}'))
        class Client:
            def __init__(self):
                self.calls = []
                self.responses = [completion(calls=[call]), completion('前序遍历为根、左、右')]
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
            async def create(self, **kwargs):
                self.calls.append(kwargs)
                return self.responses.pop(0)
        class Rag:
            async def search_with_rewrite(self, tool, query, top_k=5):
                return SimpleNamespace(success=True, data=[{'title':'二叉树讲义', 'content':'根、左、右'}], reranked=True)
        client = Client()
        agent = KnowledgeAgent(client, 'test')
        agent.set_shared_tools(build_shared_rag_tools(Rag()))
        result = asyncio.run(agent.handle(Request('解释一下二叉树', 's', 'c', intent=IntentCategory.KNOWLEDGE_QUERY)))
        self.assertTrue(result.success)
        self.assertEqual(result.tools_used, ['search_knowledge_base'])
        self.assertEqual(len(client.calls), 2)
        self.assertTrue(any(m['role'] == 'tool' for m in client.calls[1]['messages']))


if __name__ == '__main__':
    unittest.main()
