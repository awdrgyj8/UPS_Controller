<script setup>
import { computed, onMounted, ref } from 'vue'
import Icon from '../components/Icon.vue'
import StatusPill from '../components/StatusPill.vue'
import TestResults from '../components/TestResults.vue'
import TopologyGraph from '../components/TopologyGraph.vue'
import FlowStepper from '../components/FlowStepper.vue'
import { PHASE_LEVEL, TEST_STATUS, act, store } from '../store.js'
import { api } from '../api.js'
import { clock, duration } from '../format.js'

const s = computed(() => store.state)
const isSim = computed(() => s.value.mode === 'simulation')
const TABS = [
  { id: 'selftest', label: '系統自檢', icon: 'shield' },
  { id: 'drill', label: '停電演練（乾跑）', icon: 'activity' },
  { id: 'scenarios', label: '情境測試', icon: 'flask' },
  { id: 'simulator', label: '模擬器控制台', icon: 'zap' },
]
const tab = ref(new URLSearchParams(location.hash.split('?')[1] || '').get('tab') || 'selftest')

// ---- 自檢 / 演練 ----
const diag = computed(() => s.value.diagnostics)
const diagFor = (kind) => (diag.value?.kind === kind ? diag.value : null)
async function runDiagnostics(kind) {
  await act(`/api/diagnostics/${kind}`, undefined, kind === 'selftest' ? '開始系統自檢' : '開始停電演練')
}
function summary(result) {
  const counts = result?.summary || {}
  return ['pass', 'warn', 'fail', 'skip'].filter((k) => counts[k]).map((k) => ({ key: k, count: counts[k], ...TEST_STATUS[k] }))
}

// ---- 情境 ----
const scenarios = ref([])
onMounted(async () => {
  if (isSim.value) {
    try {
      scenarios.value = (await api('/api/sim/scenarios')).scenarios
    } catch {
      /* ignore */
    }
  }
})
const scenario = computed(() => s.value.scenario)
const RESULT = {
  running: { level: 'info', label: '執行中' },
  pass: { level: 'good', label: '通過' },
  warn: { level: 'warning', label: '通過（有發現）' },
  fail: { level: 'critical', label: '失敗' },
  cancelled: { level: 'neutral', label: '已停止' },
}
async function runScenario(id) {
  await act(`/api/sim/scenarios/${id}`, undefined, '情境測試開始')
}

// ---- 模擬器 ----
const sim = computed(() => s.value.simulation)
const batteryDraft = ref(null)
const SPEEDS = [1, 5, 10, 20, 50, 100]
const simAction = (path, body, message) => act(`/api/sim/${path}`, body, message)
async function commitBattery() {
  if (batteryDraft.value === null) return
  await simAction('battery', { value: Number(batteryDraft.value) })
  batteryDraft.value = null
}
const POWER = { on: '開機', off: '關機', booting: '開機中', shutting_down: '關機中' }
</script>

<template>
  <div class="grid">
    <div class="tabs" role="tablist">
      <button v-for="t in TABS" :key="t.id" role="tab" :aria-selected="tab === t.id" :class="{ active: tab === t.id }"
              :data-tab="t.id" @click="tab = t.id">
        <Icon :name="t.icon" :size="15" />{{ t.label }}
        <span v-if="!isSim && (t.id === 'scenarios' || t.id === 'simulator')" class="chip">需模擬模式</span>
      </button>
    </div>

    <!-- 系統自檢 -->
    <section v-if="tab === 'selftest'" class="card">
      <div class="card-header">
        <h2 class="card-title">系統自檢</h2>
        <span class="card-sub">檢查設定、UPS/NUT、Pterodactyl API、每個 Agent 的連線與簽章；不會對任何設備造成影響</span>
        <span class="spacer"></span>
        <button class="btn primary" :disabled="diag?.running" data-testid="run-selftest" @click="runDiagnostics('selftest')">
          <Icon :name="diag?.running && diag.kind === 'selftest' ? 'loader' : 'play'" :size="14" />執行完整自檢
        </button>
      </div>
      <div class="card-body">
        <template v-if="diagFor('selftest')">
          <div class="summary">
            <StatusPill v-if="diagFor('selftest').running" level="info" label="執行中…" />
            <StatusPill v-for="item in summary(diagFor('selftest'))" :key="item.key" :level="item.level" :label="`${item.label} ${item.count}`" />
            <span class="muted small">開始於 {{ clock(diagFor('selftest').started_at) }}</span>
          </div>
          <TestResults :results="diagFor('selftest').results" />
        </template>
        <div v-else class="empty">
          <Icon name="shield" :size="28" />
          <p>按下「執行完整自檢」檢查整個系統是否已正確設定</p>
        </div>
      </div>
    </section>

    <!-- 停電演練 -->
    <section v-if="tab === 'drill'" class="card">
      <div class="card-header">
        <h2 class="card-title">停電演練（乾跑）</h2>
        <span class="card-sub">逐步走過關機與復電流程：讀取類操作實際執行，會造成影響的動作（stop、關機、WOL）只驗證不送出</span>
        <span class="spacer"></span>
        <button class="btn primary" :disabled="diag?.running" data-testid="run-drill" @click="runDiagnostics('drill')">
          <Icon :name="diag?.running && diag.kind === 'drill' ? 'loader' : 'play'" :size="14" />開始演練
        </button>
      </div>
      <div class="card-body">
        <div class="notice info drill-note">
          <Icon name="info" :size="16" />
          <span>節點關機步驟會改送 <code>/verify</code> 簽章請求（Agent 只驗證簽章、時間戳與 nonce，不會關機），
            需要更新 UPS_Agent 才支援；舊版 Agent 會顯示警告。</span>
        </div>
        <template v-if="diagFor('drill')">
          <div class="summary">
            <StatusPill v-if="diagFor('drill').running" level="info" label="執行中…" />
            <StatusPill v-for="item in summary(diagFor('drill'))" :key="item.key" :level="item.level" :label="`${item.label} ${item.count}`" />
          </div>
          <TestResults :results="diagFor('drill').results" />
        </template>
      </div>
    </section>

    <!-- 情境測試 -->
    <template v-if="tab === 'scenarios'">
      <div v-if="!isSim" class="card card-body">
        <div class="notice warning">
          <Icon name="alert" :size="16" />
          <div>
            情境測試會真的執行停電關機與 WOL 流程，因此只在模擬模式提供。以模擬模式啟動 Controller：
            <pre class="mono">uv run main.py --simulate</pre>
          </div>
        </div>
      </div>
      <template v-else>
        <section class="scenario-list">
          <article v-for="item in scenarios" :key="item.id" class="card scenario">
            <h3>{{ item.title }}</h3>
            <p class="secondary">{{ item.description }}</p>
            <button class="btn primary small" :disabled="scenario?.running" :data-scenario="item.id" @click="runScenario(item.id)">
              <Icon name="play" :size="13" />執行
            </button>
          </article>
        </section>

        <section v-if="scenario" class="grid cols-3">
          <div class="card">
            <div class="card-header">
              <h2 class="card-title">{{ scenario.title }}</h2>
              <StatusPill :level="RESULT[scenario.result].level" :label="RESULT[scenario.result].label" data-testid="scenario-result" />
              <span class="spacer"></span>
              <button v-if="scenario.running" class="btn small danger" @click="runScenario('cancel')">
                <Icon name="stop" :size="12" />停止
              </button>
            </div>
            <div class="card-body">
              <div class="muted small">
                開始於 {{ clock(scenario.started_at) }} · 已耗時 {{ duration((scenario.finished_at || store.now) - scenario.started_at) }}
              </div>
              <ol class="steps">
                <li v-for="(step, i) in scenario.steps" :key="i" :class="TEST_STATUS[step.status]?.level">
                  <span class="badge"><Icon :name="TEST_STATUS[step.status]?.icon" :size="11" :stroke="3" /></span>
                  <div>
                    <div class="step-label">{{ step.label }}</div>
                    <div v-if="step.detail" class="step-detail">{{ step.detail }}</div>
                  </div>
                  <span class="muted small tabular">{{ step.duration_ms != null ? (step.duration_ms / 1000).toFixed(1) + 's' : '' }}</span>
                </li>
              </ol>
              <div v-if="!scenario.running" class="notice" :class="{ warning: scenario.result === 'warn', critical: scenario.result === 'fail' }">
                {{ scenario.detail }}
              </div>
            </div>
          </div>
          <div class="card span-2">
            <div class="card-header">
              <h2 class="card-title">即時畫面</h2>
              <StatusPill :level="PHASE_LEVEL[s.controller.phase]" :label="s.controller.phase_label" />
              <span class="muted small">{{ s.controller.decision }}</span>
            </div>
            <div class="card-body live">
              <div class="live-stats">
                <div><span class="muted">市電</span><strong>{{ sim.grid_online ? '正常' : '中斷' }}</strong></div>
                <div><span class="muted">電量</span><strong class="tabular">{{ sim.battery.toFixed(1) }}%</strong></div>
                <div><span class="muted">負載</span><strong class="tabular">{{ sim.load }}%</strong></div>
                <div><span class="muted">放電倍速</span><strong>×{{ sim.speed }}</strong></div>
                <div><span class="muted">WOL 封包</span><strong class="tabular">{{ sim.wol_packets }}</strong></div>
              </div>
              <TopologyGraph :state="s" compact />
              <FlowStepper :sequence="s.controller.sequence" />
            </div>
          </div>
        </section>
      </template>
    </template>

    <!-- 模擬器 -->
    <template v-if="tab === 'simulator'">
      <div v-if="!isSim" class="card card-body">
        <div class="notice warning">
          <Icon name="alert" :size="16" />
          <div>模擬器控制台只在模擬模式提供：<pre class="mono">uv run main.py --simulate</pre></div>
        </div>
      </div>
      <section v-else class="grid cols-2">
        <div class="card">
          <div class="card-header">
            <h2 class="card-title">電力與 UPS</h2>
            <span class="spacer"></span>
            <button class="btn small" @click="simAction('reset', undefined, '模擬環境已重設')"><Icon name="refresh" :size="13" />重設全部</button>
          </div>
          <div class="card-body controls">
            <div class="control">
              <div>
                <div class="control-title">市電</div>
                <div class="muted small">切斷後 UPS 改由電池供電，電量依負載下降</div>
              </div>
              <button class="btn" :class="sim.grid_online ? 'danger' : 'primary'" data-testid="toggle-grid"
                      @click="simAction('grid', { value: !sim.grid_online }, sim.grid_online ? '已切斷市電' : '已恢復市電')">
                <Icon :name="sim.grid_online ? 'x' : 'plug'" :size="14" />{{ sim.grid_online ? '切斷市電' : '恢復市電' }}
              </button>
            </div>
            <div class="control column">
              <div class="control-title">電池電量：<span class="tabular">{{ batteryDraft ?? sim.battery.toFixed(1) }}%</span>
                <span class="muted small">（關機門檻 {{ s.settings.shutdown_battery_threshold }}%）</span></div>
              <input type="range" min="0" max="100" step="1" :value="batteryDraft ?? sim.battery"
                     @input="batteryDraft = $event.target.value" @change="commitBattery" />
            </div>
            <div class="control">
              <div>
                <div class="control-title">放電 / 充電倍速</div>
                <div class="muted small">滿電續航約 {{ duration(sim.runtime, true) }}（目前負載 {{ sim.load }}%）</div>
              </div>
              <div class="segmented">
                <button v-for="v in SPEEDS" :key="v" :class="{ active: sim.speed === v }" @click="simAction('speed', { value: v })">×{{ v }}</button>
              </div>
            </div>
            <div class="control">
              <div>
                <div class="control-title">NUT Server</div>
                <div class="muted small">模擬 NUT 無回應</div>
              </div>
              <button class="btn" :class="{ danger: sim.nut_reachable }" @click="simAction('nut', { value: !sim.nut_reachable })">
                {{ sim.nut_reachable ? '中斷 NUT' : '恢復 NUT' }}
              </button>
            </div>
            <div class="control">
              <div>
                <div class="control-title">Pterodactyl 面板</div>
                <div class="muted small">模擬面板 API 無法連線</div>
              </div>
              <button class="btn" :class="{ danger: sim.ptero_reachable }" @click="simAction('ptero', { value: !sim.ptero_reachable })">
                {{ sim.ptero_reachable ? '中斷面板' : '恢復面板' }}
              </button>
            </div>
            <div v-if="sim.depleted" class="notice critical"><Icon name="alert" :size="16" />UPS 電池已耗盡，所有節點斷電</div>
          </div>
        </div>

        <div class="card">
          <div class="card-header"><h2 class="card-title">節點與伺服器故障注入</h2></div>
          <div class="card-body table-wrap">
            <table class="table">
              <thead><tr><th>節點</th><th>模擬電源</th><th>故障</th><th class="num">關機請求</th><th class="num">WOL</th></tr></thead>
              <tbody>
                <tr v-for="agent in sim.agents" :key="agent.index">
                  <td>{{ agent.name }}<div class="muted mono small">{{ agent.mac }}</div></td>
                  <td>{{ POWER[agent.power] }}<span v-if="agent.timer > 0" class="muted small">（{{ agent.timer }}s）</span></td>
                  <td>
                    <select class="select" :value="agent.fault" @change="simAction(`agents/${agent.index}/fault`, { fault: $event.target.value })">
                      <option v-for="(label, key) in sim.agent_faults" :key="key" :value="key">{{ label }}</option>
                    </select>
                  </td>
                  <td class="num">{{ agent.shutdown_requests }}</td>
                  <td class="num">{{ agent.wol_received }}</td>
                </tr>
              </tbody>
            </table>
            <h4 class="section-title servers-title">遊戲伺服器</h4>
            <div class="server-chips">
              <button v-for="server in sim.servers" :key="server.identifier" class="btn small" :class="{ danger: server.stuck }"
                      :title="server.stuck ? '點擊恢復正常' : '點擊設為無法關閉'"
                      @click="simAction(`servers/${server.identifier}/stuck`, { value: !server.stuck })">
                <span class="sdot" :class="server.state"></span>{{ server.name }}{{ server.stuck ? '（卡住）' : '' }}
              </button>
            </div>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--border);
  overflow-x: auto;
}
.tabs button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 14px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  cursor: pointer;
  color: var(--text-2);
  font-weight: 500;
  white-space: nowrap;
}
.tabs button.active {
  color: var(--text);
  border-bottom-color: var(--accent);
}
.summary {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.small {
  font-size: 12px;
}
.empty p {
  margin: 8px 0 0;
}
.drill-note {
  margin-bottom: 14px;
}
pre {
  margin: 6px 0 0;
  padding: 8px 10px;
  background: var(--surface-2);
  border-radius: 6px;
}
.scenario-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}
.scenario {
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.scenario h3 {
  margin: 0;
  font-size: 14px;
}
.scenario p {
  margin: 0;
  font-size: 12.5px;
  flex: 1;
}
.scenario .btn {
  align-self: flex-start;
}
.steps {
  list-style: none;
  margin: 12px 0;
  padding: 0;
  display: grid;
  gap: 8px;
}
.steps li {
  display: grid;
  grid-template-columns: 20px 1fr auto;
  gap: 8px;
  align-items: start;
  --c: var(--neutral);
}
.steps li.good { --c: var(--good); }
.steps li.warning { --c: var(--warning); }
.steps li.critical { --c: var(--critical); }
.steps li.info { --c: var(--info); }
.badge {
  display: inline-grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--c);
  color: #fff;
}
.steps li.warning .badge {
  color: #0b0b0b;
}
.step-label {
  font-size: 13px;
  font-weight: 500;
}
.step-detail {
  font-size: 12px;
  color: var(--text-2);
  overflow-wrap: anywhere;
}
.live {
  display: grid;
  gap: 16px;
}
.live-stats {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
}
.live-stats div {
  display: flex;
  flex-direction: column;
  font-size: 12px;
}
.live-stats strong {
  font-size: 18px;
}
.controls {
  display: grid;
  gap: 4px;
}
.control {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}
.control.column {
  flex-direction: column;
  align-items: stretch;
}
.control-title {
  font-weight: 600;
}
input[type='range'] {
  width: 100%;
  accent-color: var(--accent);
}
.servers-title {
  margin-top: 16px;
}
.server-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.sdot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--neutral);
}
.sdot.running { background: var(--good); }
.sdot.stopping, .sdot.starting { background: var(--warning); }
</style>
