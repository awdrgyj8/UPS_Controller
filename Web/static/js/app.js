import { computed, onMounted, ref } from 'vue'
import OverviewView from './views/overview.js'
import TopologyView from './views/topology.js'
import UpsView from './views/ups.js'
import NodesView from './views/nodes.js'
import TestsView from './views/tests.js'
import LogsView from './views/logs.js'
import { act, connect, store } from './store.js'
import { setToken } from './api.js'
import { duration } from './format.js'

const ROUTES = [
  { id: 'overview', label: '總覽', component: OverviewView },
  { id: 'topology', label: '連線拓撲', component: TopologyView },
  { id: 'ups', label: 'UPS 數據', component: UpsView },
  { id: 'nodes', label: '節點與伺服器', component: NodesView },
  { id: 'tests', label: '測試中心', component: TestsView },
  { id: 'logs', label: '事件紀錄', component: LogsView },
]

// 一句話講現在的狀況；「停電」另外補上已經停了多久
const HEADLINES = {
  starting: '啟動中',
  monitoring: '市電供電中',
  on_battery: '停電',
  shutdown: '正在關機',
  nodes_off: '節點已關機',
  waking: '正在喚醒節點',
  nut_error: '讀不到 UPS',
  paused: '自動控制已暫停',
}
// 這幾個階段標題已經講完了，不必再重複控制器的說明
const SELF_EXPLANATORY = new Set(['starting', 'monitoring', 'on_battery'])
const THEME_KEY = 'ups-controller-theme'

export default {
  name: 'App',
  setup() {
    const route = ref('overview')
    function readHash() {
      const id = location.hash.replace(/^#\/?/, '').split('?')[0]
      route.value = ROUTES.some((r) => r.id === id) ? id : 'overview'
    }
    window.addEventListener('hashchange', readHash)
    readHash()
    const current = computed(() => ROUTES.find((r) => r.id === route.value))

    const theme = ref(document.documentElement.dataset.theme)
    function toggleTheme() {
      theme.value = theme.value === 'dark' ? 'light' : 'dark'
      document.documentElement.dataset.theme = theme.value
      try {
        localStorage.setItem(THEME_KEY, theme.value)
      } catch {
        /* 無法儲存時只在本次頁面有效 */
      }
    }

    onMounted(connect)

    const s = computed(() => store.state)
    const controller = computed(() => s.value?.controller)
    const isSim = computed(() => s.value?.mode === 'simulation')
    const headline = computed(() => {
      const c = controller.value
      if (!c) return ''
      const text = HEADLINES[c.phase] || c.phase_label
      const since = s.value.ups?.on_battery_since
      return c.phase === 'on_battery' && since ? `${text} ${duration(store.now - since)}` : text
    })
    const note = computed(() => {
      const c = controller.value
      if (!c || SELF_EXPLANATORY.has(c.phase)) return ''
      return c.decision
    })

    const tokenInput = ref('')
    function saveToken() {
      setToken(tokenInput.value.trim())
      connect()
    }
    async function togglePause() {
      const pausing = !controller.value.paused
      if (pausing && !confirm('暫停後停電時不會自動關閉節點。確定暫停？')) return
      await act('/api/control/pause', { value: pausing }, pausing ? '已暫停自動控制' : '已恢復自動控制')
    }
    const check = () => act('/api/control/poll', undefined, '已檢查')

    return { ROUTES, route, current, theme, toggleTheme, store, s, controller, isSim, headline, note, tokenInput, saveToken, togglePause, check }
  },
  template: /* html */ `
    <div class="wrap">
      <header class="top">
        <a class="brand" href="#/overview">
          <span class="brand-mark"><Icon name="zap" :size="18" :stroke="2.6" /></span>UPS Controller
        </a>
        <nav class="nav" aria-label="主選單">
          <a v-for="r in ROUTES" :key="r.id" :href="'#/' + r.id" :data-nav="r.id"
             :aria-current="route === r.id ? 'page' : null">{{ r.label }}</a>
        </nav>
        <div class="top-end">
          <span v-if="isSim" class="chip sim">模擬模式</span>
          <span class="chip" :class="store.connected ? 'good' : 'off'" data-testid="connection">
            <span class="dot" :class="store.connected ? 'good' : 'critical'"></span>{{ store.connected ? '已連線' : '連線中斷' }}
          </span>
          <button class="icon-btn" :aria-label="theme === 'dark' ? '切換成淺色' : '切換成深色'" @click="toggleTheme">
            <Icon :name="theme === 'dark' ? 'sun' : 'moon'" :size="17" />
          </button>
        </div>
      </header>

      <div v-if="controller" class="lede" :class="{ compact: route !== 'overview' }">
        <div>
          <h1 data-testid="headline" :data-phase="controller.phase">{{ headline }}</h1>
          <p v-if="note" class="lede-note" data-testid="decision">{{ note }}</p>
        </div>
        <div class="actions">
          <button class="btn" @click="check">立即檢查</button>
          <button class="btn solid" data-testid="pause" @click="togglePause">
            {{ controller.paused ? '恢復自動控制' : '暫停自動控制' }}
          </button>
        </div>
      </div>

      <div v-if="store.error" class="notice critical">{{ store.error }}</div>
      <component :is="current.component" v-if="s" />
      <div v-else-if="!store.needToken" class="empty">正在連線到 Controller</div>

      <div class="toasts" aria-live="polite">
        <div v-for="t in store.toasts" :key="t.id" class="toast" :class="t.level">{{ t.message }}</div>
      </div>

      <div v-if="store.needToken" class="overlay">
        <form class="dialog" @submit.prevent="saveToken">
          <h2 class="title">輸入存取權杖</h2>
          <input v-model="tokenInput" class="input" type="password" placeholder="WEB_TOKEN" aria-label="WEB_TOKEN" autofocus />
          <button class="btn solid" type="submit">連線</button>
        </form>
      </div>
    </div>`,
}
