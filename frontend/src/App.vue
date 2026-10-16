<template>
  <main class="app-shell">
    <aside class="sidebar">
      <section class="brand">
        <div class="brand-mark">CP</div>
        <div>
          <h1>CoursePilot（课航）</h1>
          <p>课程咨询 · 选课规划 · 教务办理 · 费用权益</p>
        </div>
      </section>

      <section class="profile-card">
        <span>培训机构学员服务</span>
        <strong>从了解课程，到完成教务申请</strong>
        <em>说说你的目标、时间安排或想办理的事项。</em>
      </section>

      <section class="panel">
        <div class="panel-heading">
          <h2>连接设置</h2>
          <span class="pill">{{ currentBackend.label }}</span>
        </div>
        <div class="segmented">
          <button :disabled="busy" :class="{ active: settings.backend === 'python' }" @click="switchBackend('python')">Python 教育版</button>
          <button :disabled="busy" :class="{ active: settings.backend === 'java' }" @click="switchBackend('java')">Java 旧版</button>
        </div>

        <label>
          <span>Java API</span>
          <input v-model="settings.endpoints.java" :disabled="busy" @change="persist" placeholder="/api/java" />
        </label>
        <label>
          <span>Python API</span>
          <input v-model="settings.endpoints.python" :disabled="busy" @change="persist" placeholder="/api/python" />
        </label>
        <label>
          <span>学生 ID</span>
          <input v-model="settings.userId" :disabled="busy" @change="newConversation" placeholder="student_demo" />
        </label>
        <label>
          <span>会话 ID</span>
          <input v-model="settings.conversationId" :disabled="busy" @change="messages = []; persist()" placeholder="自动生成" />
        </label>

        <div class="actions">
          <button @click="checkHealth">健康检查</button>
          <button @click="loadStats">刷新状态</button>
        </div>
      </section>

      <section class="panel status-panel">
        <div class="panel-heading">
          <h2>状态</h2>
          <span :class="['status-dot', healthOk ? 'online' : 'offline']"></span>
        </div>
        <dl>
          <div>
            <dt>当前后端</dt>
            <dd>{{ currentBackend.label }}</dd>
          </div>
          <div>
            <dt>健康状态</dt>
            <dd :class="healthOk ? 'ok' : 'muted'">{{ healthLabel }}</dd>
          </div>
          <div>
            <dt>知识片段</dt>
            <dd>{{ knowledgeCount }}</dd>
          </div>
        </dl>
        <pre v-if="statusText">{{ statusText }}</pre>
      </section>
    </aside>

    <section class="workspace">
      <header class="workspace-header">
        <div>
          <span class="eyebrow">CoursePilot · 课程与教务助手</span>
          <h2>今天想学点什么？</h2>
          <p>{{ settings.backend === 'python' ? '查询课程与费用，筛选班级，确认后提交转班申请。' : 'Java 尚未同步教育能力，仅供旧版调试。' }}</p>
        </div>
        <div class="header-actions">
          <button :disabled="busy" @click="newConversation">新对话</button>
          <a :href="docsUrl" target="_blank" rel="noreferrer">API 文档</a>
        </div>
      </header>

      <section class="chat-panel">
        <div class="messages" ref="messageList" role="log" aria-live="polite" aria-label="教务对话">
          <article v-for="item in messages" :key="item.id" :class="['message', item.role]">
            <div class="message-meta">
              <span>{{ item.role === 'user' ? '我' : (item.speaker || '教务助手') }}</span>
              <small v-if="item.meta">{{ item.meta }}</small>
            </div>
            <p>{{ item.content }}</p>
            <details v-if="item.routingReason"><summary>查看分工依据</summary><p>{{ item.routingReason }}</p></details>
          </article>
          <div v-if="messages.length === 0" class="empty-state">
            <h3>课程和教务，直接说出你的需求</h3>
            <p>选一个示例，或直接说说你的问题。</p>
            <div class="example-grid">
              <button v-for="example in examples" :key="example.label" :disabled="busy" @click="draft = example.message">{{ example.label }}<small>{{ example.message }}</small></button>
            </div>
            <p class="muted">演示数据：student_demo 已报名 Python 周六班；申请仅保存为待审核，不转班、不扣款。</p>
          </div>
        </div>

        <form class="composer" @submit.prevent="sendMessage">
          <textarea v-model="draft" rows="3" aria-label="课程或教务需求" placeholder="例如：帮我转到周日的班，最好不要额外花钱"></textarea>
          <button :disabled="busy || !draft.trim()">{{ busy ? '处理中…' : '发送' }}</button>
        </form>
      </section>

      <section class="tools-grid">
        <article class="tool-panel">
          <div class="panel-heading">
            <h2>查找课程资料</h2>
            <span class="pill soft">RAG</span>
          </div>
          <div class="inline-form">
            <input v-model="searchQuery" aria-label="资料检索关键词" placeholder="二叉树的前序遍历" />
            <button @click="searchKnowledge" :disabled="busy || !searchQuery.trim()">检索</button>
          </div>
          <div class="result-list">
            <article v-for="item in searchResults" :key="item.id || item.title" class="result-item">
              <strong>{{ item.title || '未命名结果' }}</strong>
              <span>score {{ item.score ?? '-' }}</span>
              <p>{{ item.content }}</p>
            </article>
          </div>
        </article>

        <article class="tool-panel">
          <div class="panel-heading">
            <h2>导入讲义与通知</h2>
            <span class="pill soft">Docs</span>
          </div>
          <label>
            <span>标题</span>
            <input v-model="docTitle" placeholder="例如：数据结构·二叉树讲义" />
          </label>
          <label>
            <span>内容</span>
            <textarea v-model="docContent" rows="5" placeholder="粘贴讲义或教务通知，建议注明学科、章节、来源和日期"></textarea>
          </label>
          <div class="actions">
            <button @click="submitKnowledge" :disabled="busy || !docTitle.trim() || !docContent.trim()">添加文档</button>
            <label class="file-button">
              上传文件
              <input type="file" accept=".txt,.md,.json" :disabled="busy" @change="handleUpload" />
            </label>
          </div>
        </article>
      </section>
      <section class="tool-panel" v-if="settings.backend === 'python'">
        <div class="panel-heading"><h2>教育场景评测</h2><span class="pill soft">开发者工具</span></div>
        <p>验证意图识别与回复质量。会调用已配置的模型，产生 API 用量，可能需要几分钟。</p>
        <button :disabled="busy" @click="runEvaluation">{{ evaluating ? '评测中…' : '运行教育评测' }}</button>
        <p v-if="evaluationError" role="alert">{{ evaluationError }}</p>
        <div v-if="evaluation">
          <p>通过 {{ evaluation.passed }} / {{ evaluation.total }} 项 · 通过率 {{ Math.round(evaluation.pass_rate * 100) }}%</p>
          <details><summary>查看完整报告</summary><pre>{{ JSON.stringify(evaluation, null, 2) }}</pre></details>
        </div>
      </section>
    </section>
  </main>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import {
  addKnowledge,
  agentLabels,
  intentLabels,
  requestEvaluation,
  backendMeta,
  createInitialSettings,
  requestChat,
  requestHealth,
  requestKnowledgeStats,
  requestMonitor,
  requestSearch,
  saveSettings,
  uploadKnowledge
} from './lib/backends'

const settings = reactive(createInitialSettings())
const messages = ref([])
const draft = ref('')
const busy = ref(false)
const healthOk = ref(false)
const healthLabel = ref('未检查')
const statusText = ref('')
const knowledgeCount = ref('-')
const searchQuery = ref('转班规定和费用')
const searchResults = ref([])
const docTitle = ref('')
const docContent = ref('')
const evaluation = ref(null)
const evaluationError = ref('')
const evaluating = ref(false)
const examples = [
  { label: '课程咨询', message: '转班有什么规定？' },
  { label: '选课规划', message: '我零基础，只有周末有空，推荐什么课程？' },
  { label: '教务办理', message: '帮我转到周日的班，最好不要额外花钱' },
  { label: '免费资格核验', message: '我是否符合免费转班条件？' },
  { label: '带条件选班', message: '帮我转到周日班，不想补钱，老师最好不变' },
  { label: '费用与权益', message: '我还剩几节课？' },
  { label: '申请进度', message: '我上次申请怎么样了？' }
]
const messageList = ref(null)

const currentBackend = computed(() => backendMeta(settings.backend, settings))
const docsUrl = computed(() => {
  if (settings.backend === 'java') return `${currentBackend.value.baseUrl}/docs`
  return `${currentBackend.value.baseUrl}/docs`
})

watch(
  () => settings.conversationId,
  () => persist()
)

onMounted(() => {
  checkHealth()
  loadStats()
})

function switchBackend(type) {
  if (busy.value || type === settings.backend) return
  settings.backend = type
  newConversation()
  evaluation.value = null
  evaluationError.value = ''
  knowledgeCount.value = '-'
  persist()
  healthOk.value = false
  healthLabel.value = '未检查'
  statusText.value = ''
  searchResults.value = []
  checkHealth()
  loadStats()
}

function newConversation() {
  if (busy.value) return
  messages.value = []
  draft.value = ''
  settings.conversationId = crypto.randomUUID()
  persist()
}

async function runEvaluation() {
  if (busy.value || settings.backend !== 'python') return
  busy.value = true
  evaluating.value = true
  evaluation.value = null
  evaluationError.value = ''
  try {
    evaluation.value = await requestEvaluation(settings.backend, settings)
  } catch (error) {
    evaluationError.value = error.message
  } finally {
    evaluating.value = false
    busy.value = false
  }
}

function persist() {
  saveSettings(settings)
}

async function sendMessage() {
  const content = draft.value.trim()
  if (!content || busy.value) return
  messages.value.push({ id: crypto.randomUUID(), role: 'user', content })
  draft.value = ''
  busy.value = true
  try {
    const response = await requestChat(settings.backend, settings, content)
    if (response.conversationId && !settings.conversationId) {
      settings.conversationId = response.conversationId
      persist()
    }
    const meta = [
      intentLabels[response.intent] || response.intent,
      response.supportingAgents.length ? `协作：${response.supportingAgents.map(type => agentLabels[type] || type).join('、')}` : '',
      response.knowledgeUsed ? 'RAG' : '',
      response.escalated ? '建议人工处理' : ''
    ].filter(Boolean).join(' · ')
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'assistant',
      content: response.response,
      speaker: agentLabels[response.agentType] || response.agentType || '教务助手',
      routingReason: response.routingReason,
      meta
    })
  } catch (error) {
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'assistant',
      content: error.message,
      meta: '请求失败'
    })
  } finally {
    busy.value = false
    await nextTick()
    messageList.value?.scrollTo({ top: messageList.value.scrollHeight, behavior: 'smooth' })
  }
}

async function checkHealth() {
  const connection = `${settings.backend}:${currentBackend.value.baseUrl}`
  try {
    const data = await requestHealth(settings.backend, settings)
    if (connection !== `${settings.backend}:${currentBackend.value.baseUrl}`) return
    healthOk.value = data.status === 'ok'
    healthLabel.value = data.status || 'ok'
    statusText.value = JSON.stringify(data, null, 2)
  } catch (error) {
    if (connection !== `${settings.backend}:${currentBackend.value.baseUrl}`) return
    healthOk.value = false
    healthLabel.value = '不可用'
    statusText.value = error.message
  }
}

async function loadStats() {
  const connection = `${settings.backend}:${currentBackend.value.baseUrl}`
  try {
    const [stats, monitor] = await Promise.allSettled([
      requestKnowledgeStats(settings.backend, settings),
      requestMonitor(settings.backend, settings)
    ])
    if (connection !== `${settings.backend}:${currentBackend.value.baseUrl}`) return
    if (stats.status === 'fulfilled') {
      knowledgeCount.value = stats.value.total_chunks ?? stats.value.totalChunks ?? '-'
    }
    if (monitor.status === 'fulfilled') {
      statusText.value = JSON.stringify(monitor.value, null, 2)
    }
  } catch (error) {
    statusText.value = error.message
  }
}

async function searchKnowledge() {
  if (busy.value || !searchQuery.value.trim()) return
  searchResults.value = []
  busy.value = true
  try {
    const data = await requestSearch(settings.backend, settings, searchQuery.value, 5)
    searchResults.value = data.results || []
  } catch (error) {
    statusText.value = error.message
  } finally {
    busy.value = false
  }
}

async function submitKnowledge() {
  if (busy.value || !docTitle.value.trim() || !docContent.value.trim()) return
  busy.value = true
  try {
    const data = await addKnowledge(settings.backend, settings, [
      { title: docTitle.value.trim(), content: docContent.value.trim() }
    ])
    statusText.value = JSON.stringify(data, null, 2)
    await loadStats()
  } catch (error) {
    statusText.value = error.message
  } finally {
    busy.value = false
  }
}

async function handleUpload(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file || busy.value) return
  busy.value = true
  try {
    const data = await uploadKnowledge(settings.backend, settings, file)
    statusText.value = JSON.stringify(data, null, 2)
    await loadStats()
  } catch (error) {
    statusText.value = error.message
  } finally {
    busy.value = false
  }
}
</script>
