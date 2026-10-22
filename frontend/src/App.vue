<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { createApiClient } from './lib/http.js'
import MarkdownMessage from './components/MarkdownMessage.vue'

// Authentication is held by an HttpOnly session cookie, managed by the browser.
localStorage.removeItem('citymate.token')
const me = ref(null),
  health = ref(null),
  page = ref('explore'),
  loading = ref(false)
const error = ref(''),
  notice = ref(''),
  loginOpen = ref(false),
  phone = ref('13900000002'),
  code = ref(''),
  demoCode = ref('')
const shops = ref([]),
  categories = ref([]),
  vouchers = ref([]),
  orders = ref([]),
  appointments = ref([]),
  notes = ref([]),
  people = ref([]),
  ranking = ref([]),
  sign = ref({})
const adminStats = ref(null),
  reviewList = ref([]),
  category = ref(''),
  search = ref(''),
  budget = ref(''),
  nearby = ref(false)
const location = ref({ longitude: 121.446, latitude: 31.207 }),
  detail = ref(null),
  slots = ref([]),
  slot = ref(''),
  partySize = ref(2)
const noteForm = ref({ title: '', body: '', shop_id: '', images: [] }),
  notePage = ref(1),
  feedMode = ref(false),
  feedCursor = ref(null)
const conversation = ref(''),
  message = ref(''),
  messages = ref([]),
  chatting = ref(false),
  chatBody = ref(null)
const profile = ref({ nickname: '', bio: '' }),
  editing = ref(null),
  reviewReason = ref('')
const voucherForm = ref({
  shop_id: '',
  title: '',
  rules: '每人限领一张；演示订单，不发生真实支付。',
  price_cents: 4900,
  stock: 10,
  starts_at: '',
  ends_at: '',
})
const pending = ref([]),
  busy = ref(new Set())
const confirmationText = ref('')
let resolveConfirmation
function confirmAction(text) {
  if (resolveConfirmation) return Promise.resolve(false)
  confirmationText.value = text
  return new Promise((resolve) => {
    resolveConfirmation = resolve
  })
}
function finishConfirmation(accepted) {
  const resolve = resolveConfirmation
  resolveConfirmation = null
  confirmationText.value = ''
  resolve?.(accepted)
}
const nav = [
  { id: 'explore', name: '发现城市', mark: '01' },
  { id: 'deals', name: '限量好价', mark: '02' },
  { id: 'community', name: '城市手记', mark: '03' },
  { id: 'people', name: '同城旅人', mark: '04' },
  { id: 'orders', name: '我的行程', mark: '05' },
  { id: 'me', name: '个人空间', mark: '06' },
]
const currentTitle = computed(() => nav.find((n) => n.id === page.value)?.name || '商户工作台')
const labels = {
  processing: '正在生成',
  ready: '优惠券已生成',
  rejected: '未通过',
  cancelled: '已取消',
  draft: '待确认草稿',
  pending_review: '等待商户审核',
  approved: '预约成功',
}
const money = (value) => (Number(value || 0) / 100).toFixed(2)
const shopName = (id) => shops.value.find((s) => s.id === id)?.name || id
const categoryMark = (c) => ({ 美食: '食', 娱乐: '映', 运动: '动', 咖啡: '啡' })[c] || '城'
const imageURL = (path) => path

const api = createApiClient({
  onUnauthorized({ silent }) {
    me.value = null
    if (!silent) loginOpen.value = true
  },
})
const post = (path, body = {}) => api(path, { method: 'POST', body: JSON.stringify(body) })
const put = (path, body) => api(path, { method: 'PUT', body: JSON.stringify(body) })
async function action(key, fn) {
  if (busy.value.has(key)) return
  busy.value.add(key)
  error.value = ''
  notice.value = ''
  try {
    return await fn()
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value.delete(key)
  }
}
function requireLogin() {
  if (!me.value) {
    loginOpen.value = true
    return false
  }
  return true
}
function selectCategory(value = '') {
  category.value = value
  return action('shops', loadShops)
}

async function loadShops() {
  loading.value = true
  try {
    const params = new URLSearchParams({ category: category.value, query: search.value })
    if (budget.value !== '') params.set('budget', String(Math.round(Number(budget.value) * 100)))
    if (nearby.value) {
      params.set('longitude', location.value.longitude)
      params.set('latitude', location.value.latitude)
      params.set('radius', 10)
    }
    shops.value = await api('/shops?' + params)
  } finally {
    loading.value = false
  }
}
async function loadPersonal() {
  if (!me.value) return
  const results = await Promise.all([
    api('/orders'),
    api('/appointments'),
    api('/checkin'),
    api('/ranking'),
    api('/users'),
  ])
  ;[orders.value, appointments.value, sign.value, ranking.value, people.value] = results
}
async function switchPage(id) {
  page.value = id
  if (['community', 'people', 'orders', 'me', 'admin'].includes(id) && !requireLogin()) return
  await action('page', async () => {
    if (id === 'community') await loadNotes(true)
    if (['people', 'orders', 'me'].includes(id)) await loadPersonal()
    if (id === 'admin') {
      ;[reviewList.value, adminStats.value] = await Promise.all([
        api('/admin/appointments'),
        api('/admin/stats'),
      ])
    }
  })
}
async function sendCode() {
  await action('code', async () => {
    const d = await post('/auth/code', { phone: phone.value })
    demoCode.value = d.demo_code || ''
    code.value = d.demo_code || ''
    notice.value = d.message
  })
}
async function login() {
  await action('login', async () => {
    const d = await post('/auth/login', { phone: phone.value, code: code.value })
    me.value = d.user
    profile.value = { nickname: d.user.nickname, bio: d.user.bio }
    loginOpen.value = false
    demoCode.value = ''
    code.value = ''
    messages.value = []
    conversation.value = ''
    pending.value = []
    notes.value = []
    await loadPersonal()
    await switchPage(page.value)
    notice.value = `欢迎回来，${d.user.nickname}`
  })
}
async function logout() {
  await action('logout', async () => {
    await post('/auth/logout')
    me.value = null
    messages.value = []
    conversation.value = ''
    orders.value = []
    appointments.value = []
    pending.value = []
    notes.value = []
    page.value = 'explore'
  })
}
async function openShop(s) {
  if (!requireLogin()) return
  await action('detail', async () => {
    detail.value = await api('/shops/' + s.id)
    slots.value = await api(`/shops/${s.id}/slots`)
    slot.value = slots.value[0]?.label || ''
  })
}
function useLocation() {
  error.value = ''
  if (!navigator.geolocation) {
    error.value = '此浏览器不支持定位'
    return
  }
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      location.value = { longitude: pos.coords.longitude, latitude: pos.coords.latitude }
      nearby.value = true
      action('shops', loadShops)
    },
    () => {
      error.value = '未获得定位权限；可以使用上海演示位置查看附近商户'
    },
    { timeout: 10000 },
  )
}
async function claim(v) {
  if (!requireLogin() || !(await confirmAction(`领取“${v.title}”？这是演示订单，不发生真实支付。`)))
    return
  await action(v.id, async () => {
    const d = await post(`/vouchers/${v.id}/claim`)
    if (!pending.value.includes(d.order_id)) pending.value.push(d.order_id)
    notice.value = d.message
    await switchPage('orders')
  })
}
async function pollPending() {
  if (!me.value || !pending.value.length) return
  for (const id of [...pending.value]) {
    try {
      const d = await api('/orders/' + id)
      if (d.status !== 'processing') {
        pending.value = pending.value.filter((x) => x !== id)
        orders.value = await api('/orders')
      }
    } catch (e) {
      error.value = e.message
      break
    }
  }
}
async function makeDraft() {
  await action('draft', async () => {
    const d = await post('/appointments/drafts', {
      shop_id: detail.value.id,
      slot: slot.value,
      party_size: Number(partySize.value),
    })
    detail.value = null
    await switchPage('orders')
    notice.value = `草稿已生成，请核对时段和人数后确认。编号 ${d.id}`
  })
}
async function confirmDraft(id) {
  if (!(await confirmAction('确认提交此预约申请？需要商户审核后才能生效。'))) return
  await action(id, async () => {
    await post(`/appointments/${id}/confirm`)
    await loadPersonal()
    notice.value = '申请已提交，等待审核'
  })
}
async function cancelOrder(id) {
  if (!(await confirmAction('确认取消此演示订单并释放名额？'))) return
  await action(id, async () => {
    await post(`/orders/${id}/cancel`)
    await loadPersonal()
    notice.value = '已取消，名额将在后台恢复'
  })
}
async function loadNotes(reset = false) {
  if (!requireLogin()) return
  if (reset) {
    notePage.value = 1
    feedCursor.value = null
    notes.value = []
  }
  if (feedMode.value) {
    const d = await api(
      '/feed' + (feedCursor.value ? '?cursor=' + encodeURIComponent(feedCursor.value) : ''),
    )
    notes.value.push(...d.items)
    feedCursor.value = d.next_cursor
  } else {
    const d = await api('/notes?page=' + notePage.value)
    notes.value.push(...d)
    notePage.value++
    if (!d.length) notice.value = '已经看到最后了'
  }
}
async function toggleFeed(value) {
  feedMode.value = value
  await action('notes', () => loadNotes(true))
}
async function like(note) {
  await action('like' + note.id, async () => {
    const d = await put(`/notes/${note.id}/like`, { enabled: !note.liked })
    Object.assign(note, d)
  })
}
async function follow(person) {
  await action('follow' + person.id, async () => {
    const d = await put(`/users/${person.id}/follow`, { enabled: !person.following })
    person.following = d.following
  })
}
async function common(person) {
  await action('common', async () => {
    const d = await api(`/users/${person.id}/common`)
    notice.value = d.length
      ? '共同关注：' + d.map((u) => u.nickname).join('、')
      : '你们暂时没有共同关注'
  })
}
async function upload(event) {
  const file = event.target.files[0]
  if (!file) return
  await action('upload', async () => {
    if (noteForm.value.images.length >= 6) throw new Error('最多上传 6 张图片')
    const form = new FormData()
    form.append('file', file)
    const d = await api('/uploads', { method: 'POST', body: form })
    noteForm.value.images.push(d.url)
  })
  event.target.value = ''
}
async function publish() {
  await action('publish', async () => {
    await post('/notes', { ...noteForm.value, shop_id: noteForm.value.shop_id || null })
    noteForm.value = { title: '', body: '', shop_id: '', images: [] }
    feedMode.value = false
    await loadNotes(true)
    notice.value = '笔记已发布'
  })
}
async function checkin() {
  await action('checkin', async () => {
    sign.value = await post('/checkin')
    ranking.value = await api('/ranking')
    notice.value = sign.value.replayed ? '今天已经签到过了' : '签到成功，获得 10 积分'
  })
}
async function saveProfile() {
  await action('profile', async () => {
    me.value = await put('/me', profile.value)
    notice.value = '资料已更新'
  })
}
async function review(a, approve) {
  await action(a.id, async () => {
    await post(`/admin/appointments/${a.id}/review`, { approve, reason: reviewReason.value })
    await switchPage('admin')
    notice.value = approve ? '预约已批准' : '申请已拒绝'
  })
}
async function editShop() {
  await action('edit', async () => {
    const { id, ...values } = editing.value
    delete values.distance_km
    if (id) await put('/admin/shops/' + id, values)
    else await post('/admin/shops', values)
    editing.value = null
    await loadShops()
    categories.value = await api('/categories')
    notice.value = '商户资料已保存'
  })
}
function newShop() {
  editing.value = {
    name: '',
    category: '美食',
    description: '',
    address: '',
    longitude: 121.446,
    latitude: 31.207,
    price_cents: 9800,
    hours: '10:00–22:00',
  }
}
async function createVoucher() {
  await action('voucher', async () => {
    const values = {
      ...voucherForm.value,
      starts_at: new Date(voucherForm.value.starts_at).toISOString(),
      ends_at: new Date(voucherForm.value.ends_at).toISOString(),
    }
    await post('/admin/vouchers', values)
    vouchers.value = await api('/vouchers')
    voucherForm.value.title = ''
    notice.value = '优惠券已发布'
  })
}
function resetChat() {
  messages.value = []
  conversation.value = ''
}

async function sendChat(text) {
  if (!requireLogin() || chatting.value) return
  const content = typeof text === 'string' ? text : message.value.trim()
  if (!content) return
  message.value = ''
  messages.value.push({ role: 'user', content })
  chatting.value = true
  await nextTick()
  chatBody.value?.scrollTo({ top: chatBody.value.scrollHeight, behavior: 'smooth' })
  try {
    const d = await post('/chat', { message: content, conv_id: conversation.value || null })
    conversation.value = d.conv_id
    messages.value.push({ role: 'assistant', content: d.response, ...d })
  } catch (e) {
    messages.value.push({ role: 'assistant', content: e.message, failed: true })
  } finally {
    chatting.value = false
    await nextTick()
    chatBody.value?.scrollTo({ top: chatBody.value.scrollHeight, behavior: 'smooth' })
  }
}
const draftsFromMessage = (m) =>
  (m.tools || [])
    .filter((t) => t.tool === 'prepare_appointment' && t.result?.id)
    .map((t) => t.result)
let timer
onMounted(async () => {
  await action('init', async () => {
    ;[health.value, categories.value, vouchers.value] = await Promise.all([
      api('/health'),
      api('/categories'),
      api('/vouchers'),
    ])
    await loadShops()
    me.value = await api('/me', {}, true)
    if (me.value) {
      profile.value = { nickname: me.value.nickname, bio: me.value.bio }
      await loadPersonal()
    }
  })
  timer = setInterval(pollPending, 3000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="city-shell">
    <aside class="sidebar">
      <a class="brand" href="#" @click.prevent="switchPage('explore')"
        ><span class="brand-icon">C<span>·</span></span
        ><span>CityMate<small>让城市，离你更近</small></span></a
      >
      <p class="nav-label">探索你的日常</p>
      <nav>
        <button
          v-for="n in nav"
          :key="n.id"
          :class="{ active: page === n.id }"
          @click="switchPage(n.id)"
        >
          <span>{{ n.mark }}</span
          >{{ n.name }}<b v-if="page === n.id">↗</b></button
        ><button
          v-if="me?.role === 'admin'"
          :class="{ active: page === 'admin' }"
          @click="switchPage('admin')"
        >
          <span>07</span>商户工作台
        </button>
      </nav>
      <div class="side-bottom">
        <div class="edition">
          <span class="pulse"></span> 城市生活实验室<small>{{
            health?.demo ? '演示商户 · 无真实支付' : '城市服务平台'
          }}</small>
        </div>
        <button class="identity" @click="me ? switchPage('me') : (loginOpen = true)">
          <span class="avatar">{{ me?.nickname?.slice(0, 1) || '旅' }}</span
          ><span
            >{{ me?.nickname || '登录开启城市探索'
            }}<small>{{ me ? '查看我的空间' : '保存行程与生活灵感' }}</small></span
          ><b>↗</b>
        </button>
      </div>
    </aside>
    <div class="workspace">
      <header class="topbar">
        <div class="breadcrumb">CITY GUIDE <span>/</span> {{ currentTitle }}</div>
        <div class="header-actions">
          <span class="location-label">⌖ 上海 · 演示城市</span
          ><button v-if="!me" class="button primary small" @click="loginOpen = true">
            登录 / 注册</button
          ><button v-else class="text-button" @click="logout">退出登录</button>
        </div>
      </header>
      <div v-if="error" class="banner error" role="alert">
        {{ error }}<button @click="error = ''">×</button>
      </div>
      <div v-if="notice" class="banner notice" role="status">
        {{ notice }}<button @click="notice = ''">×</button>
      </div>
      <div class="content-layout">
        <main class="main-content">
          <template v-if="page === 'explore'">
            <section class="hero">
              <div class="hero-copy">
                <span class="eyebrow">A LITTLE CLOSER TO YOUR CITY</span>
                <h1>好生活，<br />就在下一站<span>。</span></h1>
                <p>发现街角的美味、周末的去处，<br />把每一次出门变成值得记录的日常。</p>
                <button class="button light" @click="sendChat('帮我推荐人均不超过150元的聚餐餐厅')">
                  让城市助手帮我选 <span>↗</span>
                </button>
              </div>
              <div class="city-art" aria-hidden="true">
                <div class="sun"></div>
                <div class="building b1"><i></i><i></i><i></i></div>
                <div class="building b2"><i></i><i></i></div>
                <div class="building b3"><i></i><i></i><i></i></div>
                <div class="tree"></div>
                <div class="street"></div>
                <span class="art-caption">YOUR NEXT GOOD DAY</span>
              </div>
            </section>
            <section class="section-heading">
              <div>
                <span class="eyebrow">CURATED FOR YOU</span>
                <h2>城市好去处</h2>
              </div>
              <button class="text-button" @click="action('shops', loadShops)">刷新发现 ↻</button>
            </section>
            <form class="search-bar" @submit.prevent="action('shops', loadShops)">
              <input
                v-model="search"
                placeholder="寻找餐厅、咖啡或周末灵感…"
                aria-label="搜索商户"
              /><input
                v-model="budget"
                type="number"
                min="0"
                placeholder="人均预算 ¥"
                aria-label="预算"
              /><button class="button primary">搜索</button>
            </form>
            <div class="filters">
              <button :class="{ selected: !category }" @click="selectCategory('')">全部</button
              ><button
                v-for="c in categories"
                :key="c"
                :class="{ selected: category === c }"
                @click="selectCategory(c)"
              >
                {{ c }}</button
              ><label
                ><input v-model="nearby" type="checkbox" @change="action('shops', loadShops)" />附近
                10 km</label
              ><button class="text-button" @click="useLocation">使用我的位置</button>
            </div>
            <p v-if="nearby" class="muted">
              按坐标 {{ location.longitude.toFixed(3) }},
              {{ location.latitude.toFixed(3) }} 查询；默认使用上海演示位置。
            </p>
            <div v-if="loading" class="empty">正在寻找城市好去处…</div>
            <div v-else-if="!shops.length" class="empty">
              暂时没有符合条件的商户，试试其他类别或位置。
            </div>
            <div class="shop-grid">
              <article
                v-for="(s, i) in shops"
                :key="s.id"
                class="shop-card"
                @click="openShop(s)"
                tabindex="0"
                @keydown.enter="openShop(s)"
              >
                <div class="shop-visual" :class="'scene-' + (i % 4)">
                  <span class="category-pill">{{ s.category }}</span
                  ><span class="visual-character">{{ categoryMark(s.category) }}</span
                  ><span class="visual-lines">CITYMATE SELECTION / 0{{ i + 1 }}</span
                  ><span class="round-arrow">↗</span>
                </div>
                <div class="shop-info">
                  <h3>{{ s.name }}</h3>
                  <p>{{ s.description }}</p>
                  <div class="shop-meta">
                    <span
                      >人均 <strong>¥{{ money(s.price_cents) }}</strong></span
                    ><span>{{
                      s.distance_km != null ? s.distance_km.toFixed(1) + ' km' : s.hours
                    }}</span>
                  </div>
                </div>
              </article>
            </div>
          </template>

          <template v-else-if="page === 'deals'"
            ><div class="page-intro">
              <span class="eyebrow">GOOD MOMENTS, BETTER PRICES</span>
              <h1>把好价，留给好日子。</h1>
              <p>限量体验券 · 每人每券限保留一个有效订单 · 无真实支付</p>
            </div>
            <div class="deal-grid">
              <article class="deal-card" v-for="v in vouchers" :key="v.id">
                <span class="ticket-label">CITYMATE / 限量体验</span>
                <h2>{{ v.title }}</h2>
                <p>{{ v.rules }}</p>
                <div class="deal-bottom">
                  <strong>¥{{ money(v.price_cents) }}</strong
                  ><button class="button primary" :disabled="busy.has(v.id)" @click="claim(v)">
                    领取体验券 ↗
                  </button>
                </div>
                <small>活动截止 {{ v.ends_at.slice(0, 10) }} · 余量以领取校验为准</small>
              </article>
            </div></template
          >

          <template v-else-if="page === 'community'"
            ><div class="page-intro">
              <span class="eyebrow">STORIES AROUND THE CORNER</span>
              <h1>写下你的城市手记。</h1>
              <p>发现值得分享的角落，也关注与你同频的旅人。</p>
            </div>
            <div v-if="!me" class="empty">
              <button class="button primary" @click="loginOpen = true">登录后查看社区</button>
            </div>
            <template v-else
              ><form class="panel composer" @submit.prevent="publish">
                <h3>今天，发现了什么？</h3>
                <input
                  v-model="noteForm.title"
                  maxlength="100"
                  required
                  placeholder="给这次发现起个标题"
                /><textarea
                  v-model="noteForm.body"
                  maxlength="5000"
                  required
                  rows="3"
                  placeholder="记录真实感受、路线或实用建议…"
                ></textarea>
                <div class="composer-tools">
                  <select v-model="noteForm.shop_id">
                    <option value="">不关联商户</option>
                    <option v-for="s in shops" :value="s.id">{{ s.name }}</option></select
                  ><label class="upload-button"
                    >＋ 添加图片<input
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      @change="upload" /></label
                  ><button
                    class="button primary"
                    :disabled="busy.has('publish') || busy.has('upload')"
                  >
                    发布手记
                  </button>
                </div>
                <div class="image-strip">
                  <button
                    type="button"
                    v-for="(img, i) in noteForm.images"
                    @click="noteForm.images.splice(i, 1)"
                    title="移除图片"
                  >
                    <img :src="imageURL(img)" alt="待发布图片" />
                  </button>
                </div>
              </form>
              <div class="filters">
                <button :class="{ selected: !feedMode }" @click="toggleFeed(false)">城市广场</button
                ><button :class="{ selected: feedMode }" @click="toggleFeed(true)">我的关注</button>
              </div>
              <article class="panel note" v-for="n in notes" :key="n.id">
                <div class="note-author">
                  <span class="avatar">{{ n.author.slice(0, 1) }}</span>
                  <div>
                    {{ n.author
                    }}<small
                      >{{ n.created_at.slice(0, 10) }} ·
                      {{ n.shop_id ? shopName(n.shop_id) : '城市灵感' }}</small
                    >
                  </div>
                </div>
                <h2>{{ n.title }}</h2>
                <p class="preserve">{{ n.body }}</p>
                <div class="image-strip">
                  <img v-for="img in n.images" :src="imageURL(img)" alt="探店图片" />
                </div>
                <div class="note-footer">
                  <button :class="['like-button', { liked: n.liked }]" @click="like(n)">
                    {{ n.liked ? '♥' : '♡' }} {{ n.likes }} 喜欢</button
                  ><small
                    >最早点赞：{{
                      n.first_likers.map((u) => u.nickname).join('、') || '等你来发现'
                    }}</small
                  >
                </div>
              </article>
              <div v-if="!notes.length" class="empty">
                {{
                  feedMode
                    ? '关注同城旅人后，他们的手记会出现在这里。'
                    : '还没有手记，来记录第一份城市灵感吧。'
                }}
              </div>
              <button
                v-if="!feedMode || feedCursor"
                class="button outline"
                @click="action('notes', () => loadNotes())"
              >
                继续看看
              </button></template
            ></template
          >

          <template v-else-if="page === 'people'"
            ><div class="page-intro">
              <span class="eyebrow">PEOPLE & CONNECTIONS</span>
              <h1>遇见同频的城市旅人。</h1>
              <p>关注他们的新发现，让周末多一些可能。</p>
            </div>
            <div class="people-grid">
              <article class="panel person" v-for="u in people" :key="u.id">
                <span class="avatar large">{{ u.nickname.slice(0, 1) }}</span>
                <h3>{{ u.nickname }}</h3>
                <p>{{ u.bio || '正在收集城市里的美好瞬间。' }}</p>
                <button
                  class="button"
                  :class="u.following ? 'outline' : 'primary'"
                  @click="follow(u)"
                >
                  {{ u.following ? '已关注 · 取消' : '＋ 关注' }}</button
                ><button class="text-button" @click="common(u)">查看共同关注</button>
              </article>
            </div>
            <div v-if="!me" class="empty">请先登录，发现同城旅人。</div></template
          >

          <template v-else-if="page === 'orders'"
            ><div class="section-heading">
              <div>
                <span class="eyebrow">YOUR PLANS, IN ONE PLACE</span>
                <h1>我的城市行程</h1>
              </div>
              <button class="button outline" @click="action('refresh', loadPersonal)">
                刷新状态
              </button>
            </div>
            <p class="muted">体验券为演示订单，不涉及付款；预约需商户审核。</p>
            <div class="panel order-card" v-for="id in pending" :key="id">
              <span class="status">正在生成订单</span>
              <p>受理编号 {{ id }}</p>
              <small
                >页面会自动查询结果。{{
                  health?.worker_online ? '' : '后台消费者可能尚未启动，请检查服务状态。'
                }}</small
              >
            </div>
            <h2 class="subheading">我的体验券</h2>
            <div v-if="!orders.length && !pending.length" class="empty">
              还没有体验券，去「限量好价」看看。
            </div>
            <article class="panel order-card" v-for="o in orders" :key="o.id">
              <div class="row">
                <h3>{{ vouchers.find((v) => v.id === o.voucher_id)?.title || o.voucher_id }}</h3>
                <span class="status" :class="o.status">{{ labels[o.status] || o.status }}</span>
              </div>
              <p>编号 {{ o.id }} · ¥{{ money(o.price_cents) }}</p>
              <small>{{ o.note }}</small
              ><button
                v-if="o.status === 'ready'"
                class="text-button danger"
                @click="cancelOrder(o.id)"
              >
                取消订单
              </button>
            </article>
            <h2 class="subheading">我的预约</h2>
            <div v-if="!appointments.length" class="empty">
              打开商户详情，选择时段即可创建预约草稿。
            </div>
            <article class="panel order-card" v-for="a in appointments" :key="a.id">
              <div class="row">
                <h3>{{ shopName(a.shop_id) }}</h3>
                <span class="status" :class="a.status">{{ labels[a.status] }}</span>
              </div>
              <p>{{ a.slot }} · {{ a.party_size }} 人</p>
              <small>{{ a.decision || '提交申请不立即占用名额，以审核结果为准。' }}</small
              ><button
                v-if="a.status === 'draft'"
                class="button primary small"
                @click="confirmDraft(a.id)"
              >
                确认提交预约
              </button>
            </article></template
          >

          <template v-else-if="page === 'me'"
            ><div class="page-intro">
              <span class="eyebrow">MAKE EVERY DAY COUNT</span>
              <h1>在城市里，积攒好日常。</h1>
            </div>
            <template v-if="me"
              ><section class="checkin-card">
                <div>
                  <span class="eyebrow">DAILY CHECK-IN</span>
                  <h2>
                    连续签到 <strong>{{ sign.streak || 0 }}</strong> 天
                  </h2>
                  <p>本月签到 {{ sign.month_days || 0 }} 天 · 累计 {{ sign.points || 0 }} 积分</p>
                </div>
                <button
                  class="button light"
                  :disabled="sign.signed_today || busy.has('checkin')"
                  @click="checkin"
                >
                  {{ sign.signed_today ? '今日已打卡 ✓' : '今日打卡 ＋10' }}
                </button>
              </section>
              <form class="panel profile-form" @submit.prevent="saveProfile">
                <h2>我的资料</h2>
                <label>昵称<input v-model="profile.nickname" required maxlength="80" /></label
                ><label
                  >个人介绍<textarea
                    v-model="profile.bio"
                    maxlength="500"
                    rows="2"
                  ></textarea></label
                ><button class="button primary">保存资料</button>
              </form>
              <section class="panel">
                <h2>城市探索榜</h2>
                <div class="rank-row" v-for="(r, i) in ranking" :key="r.user.id">
                  <span class="rank-index">{{ String(i + 1).padStart(2, '0') }}</span
                  ><span>{{ r.user.nickname }}</span
                  ><strong>{{ r.points }} 分</strong>
                </div>
                <p v-if="!ranking.length" class="muted">完成签到，开启你的城市积分记录。</p>
              </section></template
            >
            <div v-else class="empty">登录后开启你的个人空间。</div></template
          >

          <template v-else-if="page === 'admin' && me?.role === 'admin'"
            ><div class="page-intro">
              <span class="eyebrow">MERCHANT WORKSPACE</span>
              <h1>商户工作台</h1>
              <p>审核预约、维护商户信息、查看独立访客。</p>
            </div>
            <div class="stats-grid">
              <div class="panel">
                <small>订单消费者</small>
                <h2>{{ adminStats?.worker_online ? '在线' : '离线' }}</h2>
              </div>
              <div class="panel">
                <small>待确认队列消息</small>
                <h2>{{ adminStats?.pending?.pending || 0 }}</h2>
              </div>
            </div>
            <div class="panel">
              <h2>今日独立访客 · 近似值</h2>
              <div class="rank-row" v-for="s in adminStats?.visitors">
                <span>{{ s.shop }}</span
                ><strong>{{ s.uv_approx }}</strong>
              </div>
            </div>
            <h2 class="subheading">预约审核</h2>
            <input v-model="reviewReason" placeholder="审核说明（可选）" maxlength="250" />
            <article class="panel order-card" v-for="a in reviewList" :key="a.id">
              <div class="row">
                <h3>{{ shopName(a.shop_id) }} · {{ a.party_size }} 人</h3>
                <span class="status">{{ labels[a.status] }}</span>
              </div>
              <p>{{ a.slot }}</p>
              <div v-if="a.status === 'pending_review'" class="row">
                <button class="button primary" @click="review(a, true)">批准预约</button
                ><button class="button outline" @click="review(a, false)">拒绝申请</button>
              </div>
            </article>
            <h2 class="subheading">商户资料</h2>
            <div class="panel row" v-for="s in shops">
              <span>{{ s.name }}</span
              ><button class="text-button" @click="editing = { ...s }">编辑资料 ↗</button>
            </div></template
          >
          <section v-if="page === 'admin' && me?.role === 'admin'" class="panel">
            <div class="row">
              <h2>扩展城市服务</h2>
              <button class="button outline" @click="newShop">＋ 新增商户</button>
            </div>
            <form class="profile-form" @submit.prevent="createVoucher">
              <h3>发布限量优惠券</h3>
              <label
                >关联商户<select v-model="voucherForm.shop_id" required>
                  <option value="">请选择商户</option>
                  <option v-for="s in shops" :value="s.id">{{ s.name }}</option>
                </select></label
              ><label
                >优惠券名称<input v-model="voucherForm.title" required maxlength="160" /></label
              ><label
                >使用规则<textarea v-model="voucherForm.rules" required maxlength="3000"></textarea>
              </label>
              <div class="row">
                <label
                  >价格（分）<input
                    v-model.number="voucherForm.price_cents"
                    type="number"
                    min="0"
                    max="10000000"
                    required /></label
                ><label
                  >数量<input
                    v-model.number="voucherForm.stock"
                    type="number"
                    min="1"
                    max="100000"
                    required
                /></label>
              </div>
              <label
                >开始时间（本机时区）<input
                  v-model="voucherForm.starts_at"
                  type="datetime-local"
                  required /></label
              ><label
                >结束时间（本机时区）<input
                  v-model="voucherForm.ends_at"
                  type="datetime-local"
                  required /></label
              ><button class="button primary" :disabled="busy.has('voucher')">发布优惠券</button>
            </form>
          </section>
        </main>

        <aside class="assistant-panel">
          <div class="assistant-header">
            <span class="ai-symbol">✳</span>
            <div>
              <h3>你的城市助手</h3>
              <small>{{
                health?.ai_mode === 'llm' ? '一起发现下一站' : '规则演示模式 · 可配置大模型'
              }}</small>
            </div>
            <button class="text-button" title="新建会话" @click="resetChat">＋</button>
          </div>
          <div class="chat-body" ref="chatBody">
            <template v-if="!messages.length"
              ><div class="assistant-welcome">
                <span class="eyebrow">HELLO, CITY EXPLORER</span>
                <h2>今天，想怎么过？</h2>
                <p>告诉我预算和偏好，<br />一起找到适合你的城市去处。</p>
              </div>
              <button class="suggestion" @click="sendChat('推荐人均不超过150元的聚餐餐厅')">
                人均 150 元，朋友聚餐 <span>↗</span></button
              ><button class="suggestion" @click="sendChat('有什么限量优惠券？')">
                看看最近的限量好价 <span>↗</span></button
              ><button class="suggestion" @click="sendChat('查询我的订单状态')">
                帮我查一下订单状态 <span>↗</span>
              </button></template
            >
            <div v-for="(m, i) in messages" :key="i" class="chat-message" :class="m.role">
              <small>{{ m.role === 'user' ? '你' : 'CITYMATE' }}</small>
              <MarkdownMessage v-if="m.role === 'assistant'" :content="m.content" />
              <p v-else>{{ m.content }}</p>
              <button
                v-for="d in draftsFromMessage(m)"
                class="button primary small"
                @click="sendChat('确认预约 ' + d.id)"
              >
                确认预约 · {{ d.slot }}
              </button>
              <details v-if="m.tools?.length">
                <summary>查看依据 · {{ m.tools.length }} 次查询</summary>
                <div v-for="(t, j) in m.tools" :key="j">
                  <b>{{ t.tool }}</b>
                  <pre>{{ JSON.stringify(t.result, null, 2) }}</pre>
                </div>
              </details>
            </div>
            <div v-if="chatting" class="thinking">正在查找适合你的答案<span>…</span></div>
          </div>
          <form class="chat-input" @submit.prevent="sendChat()">
            <textarea
              v-model="message"
              placeholder="说说你的计划…"
              rows="2"
              maxlength="4000"
              @keydown.enter.exact.prevent="sendChat()"
            ></textarea>
            <div>
              <small>业务操作需明确确认</small
              ><button :disabled="chatting || !message.trim()" aria-label="发送消息">↑</button>
            </div>
          </form>
          <p class="assistant-footnote">演示资料仅用于体验，出行前请核实真实信息。</p>
        </aside>
      </div>
      <footer class="site-footer">
        CITYMATE — A LITTLE CLOSER TO YOUR CITY <span>本地生活 · Python 后端 · AI 助手</span>
      </footer>
    </div>

    <div v-if="confirmationText" class="modal-backdrop" @click.self="finishConfirmation(false)">
      <section class="modal" role="dialog" aria-modal="true" aria-label="确认操作">
        <h2>确认这一步</h2>
        <p>{{ confirmationText }}</p>
        <div class="row">
          <button class="button outline" @click="finishConfirmation(false)">暂不操作</button
          ><button class="button primary" @click="finishConfirmation(true)">确认操作</button>
        </div>
      </section>
    </div>
    <div v-if="loginOpen" class="modal-backdrop" @click.self="loginOpen = false">
      <form class="modal login-modal" @submit.prevent="login">
        <button type="button" class="modal-close" @click="loginOpen = false" aria-label="关闭">
          ×</button
        ><span class="eyebrow">WELCOME TO CITYMATE</span>
        <h2>城市的新故事，<br />从这里开始。</h2>
        <p>验证码登录，首次登录自动创建账户。</p>
        <label
          >手机号码<input
            v-model="phone"
            inputmode="tel"
            pattern="1[3-9][0-9]{9}"
            required
            placeholder="请输入手机号" /></label
        ><label
          >验证码
          <div class="code-field">
            <input
              v-model="code"
              inputmode="numeric"
              pattern="[0-9]{6}"
              required
              maxlength="6"
            /><button
              type="button"
              class="button outline"
              :disabled="busy.has('code')"
              @click="sendCode"
            >
              获取验证码
            </button>
          </div></label
        >
        <p v-if="demoCode" class="demo-hint">
          演示验证码：<strong>{{ demoCode }}</strong
          >（未发送短信）
        </p>
        <button class="button primary full" :disabled="busy.has('login')">登录，开始探索 ↗</button
        ><small v-if="health?.demo">演示管理员：13900000000；其他号码可注册普通账户。</small>
      </form>
    </div>
    <div v-if="detail" class="modal-backdrop" @click.self="detail = null">
      <section class="modal detail-modal">
        <button class="modal-close" @click="detail = null" aria-label="关闭">×</button
        ><span class="eyebrow">{{ detail.category }} / CITYMATE SELECTION</span>
        <h2>{{ detail.name }}</h2>
        <p>{{ detail.description }}</p>
        <div class="detail-facts">
          <span>⌖ {{ detail.address }}</span
          ><span>营业时间 {{ detail.hours }}</span
          ><strong>人均 ¥{{ money(detail.price_cents) }}</strong>
        </div>
        <form @submit.prevent="makeDraft">
          <h3>为下一次出门，留个位置。</h3>
          <label
            >预约时段<select v-model="slot" required>
              <option v-for="s in slots" :value="s.label">
                {{ s.label }} · 可约 {{ s.seats }} 人
              </option>
            </select></label
          ><label
            >同行人数<input v-model="partySize" type="number" min="1" max="20" required
          /></label>
          <p class="muted">先生成草稿，确认提交后等待商户审核。审核通过才会占用名额。</p>
          <button class="button primary full" :disabled="!slot || busy.has('draft')">
            生成预约草稿 ↗
          </button>
        </form>
      </section>
    </div>
    <div v-if="editing" class="modal-backdrop">
      <form class="modal" @submit.prevent="editShop">
        <button type="button" class="modal-close" @click="editing = null">×</button>
        <h2>编辑商户</h2>
        <label v-for="field in ['name', 'category', 'description', 'address', 'hours']"
          >{{
            {
              name: '名称',
              category: '类别',
              description: '介绍',
              address: '地址',
              hours: '营业时间',
            }[field]
          }}<input v-model="editing[field]" required
        /></label>
        <div class="row">
          <label
            >经度<input
              v-model.number="editing.longitude"
              type="number"
              step="any"
              min="-180"
              max="180" /></label
          ><label
            >纬度<input
              v-model.number="editing.latitude"
              type="number"
              step="any"
              min="-85"
              max="85"
          /></label>
        </div>
        <label
          >人均价格（分）<input v-model.number="editing.price_cents" type="number" min="0" /></label
        ><button class="button primary full">保存商户信息</button>
      </form>
    </div>
  </div>
</template>
