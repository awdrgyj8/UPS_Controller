<script setup>
import { computed, onMounted, ref } from 'vue'
import Icon from './components/Icon.vue'
import StatusPill from './components/StatusPill.vue'
import OverviewView from './views/OverviewView.vue'
import TopologyView from './views/TopologyView.vue'
import UpsView from './views/UpsView.vue'
import NodesView from './views/NodesView.vue'
import TestCenterView from './views/TestCenterView.vue'
import LogsView from './views/LogsView.vue'
import { PHASE_LEVEL, act, connect, store } from './store.js'
import { setToken } from './api.js'
import { ago, duration } from './format.js'

const ROUTES = [
  { id: 'overview', label: '總覽', icon: 'gauge', component: OverviewView },
  { id: 'topology', label: '連線拓撲', icon: 'topology', component: TopologyView },
  { id: 'ups', label: 'UPS 詳細數據', icon: 'battery', component: UpsView },
  { id: 'nodes', label: '節點與伺服器', icon: 'server', component: NodesView },
  { id: 'tests', label: '測試中心', icon: 'flask', component: TestCenterView },
  { id: 'logs', label: '事件紀錄', icon: 'list', component: LogsView },
]

const route = ref('overview')
const navOpen = ref(false)
function readHash() {
  const id = location.hash.replace(/^#\/?/, '').split('?')[0]
  route.value = ROUTES.some((r) => r.id === id) ? id : 'overview'
}
window.addEventListener('hashchange', readHash)
readHash()
const current = computed(() => ROUTES.find((r) => r.id === route.value))

// 主題：跟隨系統，可手動切換
const theme = ref('')
try {
  theme.value = localStorage.getItem('ups-controller-theme') || ''
} catch {
  /* ignore */
}
function applyTheme() {
  if (theme.value) document.documentElement.dataset.theme = theme.value
  else delete document.documentElement.dataset.theme
}
applyTheme()
function toggleTheme() {
  const dark = theme.value ? theme.value === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches
  theme.value = dark ? 'light' : 'dark'
  try {
    localStorage.setItem('ups-controller-theme', theme.value)
  } catch {
    /* ignore */
  }
  applyTheme()
}

onMounted(connect)

const s = computed(() => store.state)
const controller = computed(() => s.value?.controller)
const isSim = computed(() => s.value?.mode === 'simulation')
const nextPoll = computed(() => {
  if (!controller.value?.next_cycle_at) return '-'
  const left = controller.value.next_cycle_at - store.now
  return left <= 0 ? '輪詢中' : `${Math.ceil(left)} 秒後`
})

const tokenInput = ref('')
function saveToken() {
  setToken(tokenInput.value.trim())
  connect()
}

async function togglePause() {
  const pausing = !controller.value.paused
  if (pausing && !confirm('暫停後控制器只會監控，不會在停電時關閉節點，確定要暫停？')) return
  await act('/api/control/pause', { value: pausing }, pausing ? '已暫停自動控制' : '已恢復自動控制')
}
</script>

<template>
  <div class="app">
    <aside class="sidebar" :class="{ open: navOpen }">
      <div class="brand">
        <span class="logo"><Icon name="zap" :size="18" :stroke="2.4" /></span>
        <div>
          <div class="name">UPS Controller</div>
          <div class="muted small">{{ isSim ? '模擬模式' : '實機模式' }}</div>
        </div>
        <button class="btn ghost menu" aria-label="選單" @click="navOpen = !navOpen"><Icon name="menu" /></button>
      </div>
      <nav>
        <a v-for="r in ROUTES" :key="r.id" :href="`#/${r.id}`" :class="{ active: route === r.id }"
           :data-nav="r.id" @click="navOpen = false">
          <Icon :name="r.icon" :size="17" />
          {{ r.label }}
        </a>
      </nav>
      <div class="side-foot">
        <div class="conn" :class="store.connected ? 'on' : 'off'">
          <span class="dot"></span>{{ store.connected ? '即時連線中' : '連線中斷，重試中…' }}
        </div>
        <button class="btn ghost small" @click="toggleTheme"><Icon name="moon" :size="14" />切換深淺色</button>
      </div>
    </aside>

    <main>
      <header v-if="controller" class="topbar card">
        <div class="phase">
          <StatusPill size="lg" :level="PHASE_LEVEL[controller.phase] || 'neutral'" :label="controller.phase_label" />
          <div class="decision">
            <div class="decision-text" data-testid="decision">{{ controller.decision }}</div>
            <div class="muted small">
              節點預期：<strong class="secondary">{{ controller.expected_power_state === false ? '關機' : '開機' }}</strong>
              · 第 {{ controller.cycle_count }} 輪
              · 上次輪詢 {{ ago(controller.last_cycle_at, store.now) }}
              · 下次 {{ nextPoll }}
              · 已執行 {{ duration(store.now - s.started_at, true) }}
            </div>
          </div>
        </div>
        <div class="actions">
          <button class="btn" @click="act('/api/control/poll', undefined, '已觸發輪詢')">
            <Icon name="refresh" :size="14" />立即輪詢
          </button>
          <button class="btn" :class="{ danger: !controller.paused }" data-testid="pause" @click="togglePause">
            <Icon :name="controller.paused ? 'play' : 'pause'" :size="14" />
            {{ controller.paused ? '恢復自動控制' : '暫停自動控制' }}
          </button>
        </div>
      </header>

      <div v-if="isSim" class="notice info sim-banner">
        <Icon name="flask" :size="16" />
        <span><strong>模擬模式</strong>：UPS、Agent、Pterodactyl 皆為模擬資料，控制器執行的是與實機相同的控制流程，
          不會對任何真實設備送出指令。可到 <a href="#/tests">測試中心</a> 執行完整情境測試或手動注入故障。</span>
      </div>
      <div v-if="store.error" class="notice critical">{{ store.error }}</div>

      <component :is="current.component" v-if="s" />
      <div v-else class="empty">正在連線到 Controller…</div>
    </main>

    <div class="toasts">
      <div v-for="t in store.toasts" :key="t.id" class="toast" :class="t.level">
        <Icon :name="t.level === 'critical' ? 'x' : 'check'" :size="14" :stroke="3" />{{ t.message }}
      </div>
    </div>

    <div v-if="store.needToken" class="overlay">
      <form class="card dialog" @submit.prevent="saveToken">
        <h2>需要存取權杖</h2>
        <p class="secondary">此 Controller 已設定 <code>WEB_TOKEN</code>，請輸入權杖後繼續。</p>
        <input v-model="tokenInput" class="input" type="password" placeholder="WEB_TOKEN" autofocus />
        <button class="btn primary" type="submit">連線</button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.app {
  display: grid;
  grid-template-columns: 232px minmax(0, 1fr);
  min-height: 100vh;
}
.sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 18px 12px;
  border-right: 1px solid var(--border);
  background: var(--surface);
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 6px;
}
.logo {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  background: color-mix(in srgb, var(--power) 20%, var(--surface));
  color: var(--power);
}
.name {
  font-weight: 700;
  font-size: 15px;
}
.small {
  font-size: 12px;
}
.menu {
  display: none;
  margin-left: auto;
}
nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
nav a {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  color: var(--text-2);
  text-decoration: none;
  font-weight: 500;
}
nav a:hover {
  background: var(--surface-2);
  color: var(--text);
}
nav a.active {
  background: var(--surface-3);
  color: var(--text);
}
.side-foot {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 0 6px;
}
.conn {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-2);
}
.conn .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--critical);
}
.conn.on .dot {
  background: var(--good);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--good) 25%, transparent);
}
main {
  padding: 20px 24px 40px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 1600px;
  width: 100%;
}
.topbar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  flex-wrap: wrap;
}
.phase {
  display: flex;
  align-items: center;
  gap: 8px 14px;
  flex: 1 1 320px;
  flex-wrap: wrap;
  min-width: 0;
}
.decision {
  flex: 1 1 220px;
  min-width: 0;
}
.decision-text {
  font-weight: 600;
}
.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.sim-banner a {
  color: var(--accent-ink);
}
.toasts {
  position: fixed;
  right: 16px;
  bottom: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  z-index: 20;
  max-width: min(420px, calc(100vw - 32px));
}
.toast {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 10px;
  background: var(--surface-2);
  border: 1px solid var(--border-strong);
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.25);
  font-size: 13px;
}
.toast.good {
  border-color: color-mix(in srgb, var(--good) 50%, transparent);
}
.toast.critical {
  border-color: color-mix(in srgb, var(--critical) 60%, transparent);
}
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: grid;
  place-items: center;
  z-index: 30;
  padding: 16px;
}
.dialog {
  padding: 20px;
  width: min(380px, 100%);
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.dialog h2 {
  margin: 0;
  font-size: 17px;
}
.dialog p {
  margin: 0;
}

@media (max-width: 900px) {
  .app {
    grid-template-columns: minmax(0, 1fr);
  }
  .sidebar {
    position: sticky;
    height: auto;
    z-index: 10;
    padding: 10px 12px;
    gap: 8px;
  }
  .menu {
    display: inline-flex;
  }
  nav,
  .side-foot {
    display: none;
  }
  .sidebar.open nav,
  .sidebar.open .side-foot {
    display: flex;
  }
  main {
    padding: 16px;
  }
}
</style>
