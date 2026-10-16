import { test, beforeEach } from 'node:test'
import assert from 'node:assert/strict'
import { createInitialSettings, saveSettings, requestChat, requestSearch, requestEvaluation, agentLabels } from '../src/lib/backends.js'

let storage
let calls
beforeEach(() => {
  storage = new Map()
  calls = []
  globalThis.localStorage = { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value) }
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options })
    return { ok: true, text: async () => JSON.stringify({ conv_id: 'lesson-1', response: '请确认转班草稿', intent: 'academic_service', agent_type: 'academic_service', primary_agent: 'academic_service', supporting_agents: ['course_planning', 'fees_entitlements'], routing_reason: '主 Agent 汇总班级与费用', knowledge_used: true }) }
  }
})

test('education defaults do not inherit legacy Java conversation', () => {
  storage.set('coursepilot.frontend.settings', JSON.stringify({ backend: 'java', conversationId: 'old' }))
  assert.equal(createInitialSettings().backend, 'python')
  assert.equal(createInitialSettings().conversationId, '')
  const settings = createInitialSettings()
  settings.conversationId = 'new'
  saveSettings(settings)
  assert.equal(createInitialSettings().conversationId, 'new')
})

test('CoursePilot reads previous education settings and writes its new key', () => {
  storage.set('echomind.education.settings', JSON.stringify({ userId: 'student_demo', conversationId: 'saved-session' }))
  const settings = createInitialSettings()
  assert.equal(settings.conversationId, 'saved-session')
  saveSettings(settings)
  assert.equal(JSON.parse(storage.get('coursepilot.education.settings')).conversationId, 'saved-session')
})

test('Python request and education routing response use correct fields', async () => {
  const settings = createInitialSettings()
  settings.conversationId = 'lesson-1'
  const result = await requestChat('python', settings, '帮我转到周日班，不要额外花钱')
  const body = JSON.parse(calls[0].options.body)
  assert.equal(body.conv_id, 'lesson-1')
  assert.equal(body.user_id, 'student_demo')
  assert.equal(result.conversationId, 'lesson-1')
  assert.equal(agentLabels[result.agentType], '教务办理')
  assert.deepEqual(result.supportingAgents, ['course_planning', 'fees_entitlements'])
  assert.equal(result.routingReason, '主 Agent 汇总班级与费用')
})

test('search parameter names and evaluation endpoint match backends', async () => {
  const settings = createInitialSettings()
  await requestSearch('python', settings, '二叉树', 3)
  await requestSearch('java', settings, '二叉树', 4)
  await requestEvaluation('python', settings)
  assert.match(calls[0].url, /top_k=3/)
  assert.match(calls[1].url, /topK=4/)
  assert.equal(calls[2].url, '/api/python/eval/run')
  assert.equal(calls[2].options.method, 'POST')
})

test('HTTP errors surface instead of becoming empty answers', async () => {
  globalThis.fetch = async () => ({ ok: false, status: 503, statusText: 'Unavailable', text: async () => '{"detail":"服务未就绪"}' })
  await assert.rejects(requestChat('python', createInitialSettings(), '你好'), /503.*服务未就绪/)
})
