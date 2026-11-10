import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import TestResults from '../components/test-results.js'
import { TEST_STATUS, act, cleanMessage, store } from '../store.js'
import { api } from '../api.js'
import { duration } from '../format.js'

const TABS = [
  { id: 'selftest', label: '系統自檢' },
  { id: 'drill', label: '停電演練' },
  { id: 'scenarios', label: '情境測試' },
  { id: 'simulator', label: '模擬器' },
]
const SIM_ONLY = new Set(['scenarios', 'simulator'])
const tabFromHash = () => {
  const id = new URLSearchParams(location.hash.split('?')[1] || '').get('tab')
  return TABS.some((t) => t.id === id) ? id : 'selftest'
}

// ---- 自檢 / 演練共用的面板：左邊主角磚（執行與統計），右邊結果 ----
const DiagPanel = {
  name: 'DiagPanel',
  components: { TestResults },
  props: {
    kind: { type: String, required: true },
    title: { type: String, required: true },
    note: { type: String, required: true },
    action: { type: String, required: true },
    tone: { type: String, default: 'accent' },
  },
  setup(props) {
    const diag = computed(() => store.state.diagnostics)
    const mine = computed(() => (diag.value?.kind === props.kind ? diag.value : null))
    const busy = computed(() => !!diag.value?.running)
    const counts = computed(() => {
      const c = { pass: 0, warn: 0, fail: 0, skip: 0 }
      for (const r of mine.value?.results || []) if (r.status in c) c[r.status]++
      return c
    })
    const others = computed(() =>
      ['fail', 'warn', 'skip'].filter((k) => counts.value[k]).map((k) => ({ key: k, count: counts.value[k], ...TEST_STATUS[k] })),
    )
    const run = () => act(`/api/diagnostics/${props.kind}`, undefined, `${props.title}開始`)
    return { mine, busy, counts, others, run }
  },
  template: /* html */ `
    <div class="grid">
      <section class="tile hero span-4" :class="tone">
        <div class="label">{{ title }}</div>
        <div v-if="mine" class="score">
          <div class="big">{{ counts.pass }}<small>/ {{ mine.results.length }}</small></div>
          <div class="score-word">{{ mine.running ? '執行中' : '通過' }}</div>
          <div v-if="others.length" class="score-pills">
            <StatusPill v-for="item in others" :key="item.key" :level="item.level" :label="item.label + ' ' + item.count" />
          </div>
        </div>
        <div class="hero-foot">
          <p class="safe">{{ note }}</p>
          <button class="btn" :data-testid="'run-' + kind" :disabled="busy" @click="run">
            <Icon :name="mine?.running ? 'loader' : 'play'" :size="15" />{{ action }}
          </button>
        </div>
      </section>
      <section class="tile span-8">
        <TestResults v-if="mine" :results="mine.results" />
        <div v-else class="empty">還沒跑過</div>
      </section>
    </div>`,
}

const SCENARIO_RESULT = {
  running: { level: 'info', label: '執行中' },
  pass: { level: 'good', label: '通過' },
  warn: { level: 'warning', label: '通過（有發現）' },
  fail: { level: 'critical', label: '失敗' },
  cancelled: { level: 'neutral', label: '已停止' },
}
// 步驟狀態對應到 base.css .steps 的樣式；失敗的步驟另外帶 critical
const STEP_CLASS = { pass: 'good done', warn: 'warning warn', fail: 'critical failed', running: 'info running', cancelled: 'neutral', skip: 'neutral' }
const STEP_ICON = { pass: 'check', warn: 'alert', fail: 'x', running: 'loader', cancelled: 'minus', skip: 'minus' }

const FAULTS = { none: '正常', offline: '離線', reject: '拒絕簽章', slow: '高延遲', no_wol: '無法喚醒' }
const POWER = { on: '開機', off: '關機', booting: '開機中', shutting_down: '關機中' }
const SPEEDS = [1, 5, 10, 20, 50, 100]

// 市電波形：供電時是正弦波，切斷後是平線
function sinePath(flat) {
  let d = ''
  for (let x = -4; x <= 444; x += 4) d += `${d ? 'L' : 'M'}${x} ${(40 + (flat ? 0 : Math.sin((x / 440) * Math.PI * 8) * 22)).toFixed(1)}`
  return d
}
const WAVE = { live: sinePath(false), flat: sinePath(true) }

export default {
  name: 'TestsView',
  components: { DiagPanel },
  setup() {
    const s = computed(() => store.state)
    const isSim = computed(() => s.value.mode === 'simulation')

    const tab = ref(tabFromHash())
    function selectTab(id) {
      tab.value = id
      history.replaceState(null, '', `#/tests?tab=${id}`)
    }
    const onHash = () => {
      if (location.hash.startsWith('#/tests')) tab.value = tabFromHash()
    }
    window.addEventListener('hashchange', onHash)
    onBeforeUnmount(() => window.removeEventListener('hashchange', onHash))
    const locked = computed(() => SIM_ONLY.has(tab.value) && !isSim.value)

    // ---- 情境 ----
    const scenarios = ref([])
    onMounted(async () => {
      if (!isSim.value) return
      try {
        scenarios.value = (await api('/api/sim/scenarios')).scenarios
      } catch {
        /* 清單載入失敗時維持空白，其餘功能不受影響 */
      }
    })
    const scenario = computed(() => s.value.scenario)
    const scenarioResult = computed(() => SCENARIO_RESULT[scenario.value?.result] || SCENARIO_RESULT.running)
    const elapsed = computed(() => {
      const sc = scenario.value
      return sc?.started_at ? duration((sc.finished_at || store.now) - sc.started_at) : ''
    })
    const runScenario = (id) => act(`/api/sim/scenarios/${id}`, undefined, id === 'cancel' ? '已停止' : '情境開始')

    // ---- 模擬器 ----
    const sim = computed(() => s.value.simulation)
    const threshold = computed(() => s.value.settings.shutdown_battery_threshold)
    const simAction = (path, body, message) => act(`/api/sim/${path}`, body, message)
    const batteryDraft = ref(null)
    async function commitBattery() {
      if (batteryDraft.value === null) return
      await simAction('battery', { value: Number(batteryDraft.value) })
      batteryDraft.value = null
    }
    const batteryShown = computed(() => (batteryDraft.value !== null ? Number(batteryDraft.value) : sim.value.battery))
    const faultLabel = (key, fallback) => FAULTS[key] || fallback
    const isUp = (agent) => agent.power === 'on' || agent.power === 'booting'
    const powerLabel = (agent) => POWER[agent.power] + (agent.timer > 0 ? ` ${Math.ceil(agent.timer)} 秒` : '')

    return {
      TABS, SPEEDS, WAVE, STEP_CLASS, STEP_ICON, store, s, isSim, tab, selectTab, locked,
      scenarios, scenario, scenarioResult, elapsed, runScenario,
      sim, threshold, simAction, batteryDraft, commitBattery, batteryShown, faultLabel, isUp, powerLabel,
      cleanMessage, duration,
    }
  },
  template: /* html */ `
    <div class="v-tests">
      <div class="bar">
        <div class="seg" role="tablist" aria-label="測試類型">
          <button v-for="t in TABS" :key="t.id" role="tab" :aria-selected="tab === t.id" :data-tab="t.id"
                  @click="selectTab(t.id)">{{ t.label }}</button>
        </div>
        <button v-if="tab === 'simulator' && isSim" class="btn small" data-testid="sim-reset"
                @click="simAction('reset', undefined, '已重設')">
          <Icon name="refresh" :size="14" />重設模擬
        </button>
      </div>

      <DiagPanel v-if="tab === 'selftest'" kind="selftest" title="系統自檢" action="開始自檢" tone="accent"
                 note="只讀取與驗證，不影響設備" />

      <DiagPanel v-else-if="tab === 'drill'" kind="drill" title="停電演練" action="開始演練" tone="deep"
                 note="乾跑：停止伺服器、關機、WOL 只驗證，不送出" />

      <section v-else-if="locked" class="tile tint locked">
        <div class="title">只在模擬模式提供</div>
        <code class="mono">uv run main.py --simulate</code>
      </section>

      <!-- 情境測試 -->
      <div v-else-if="tab === 'scenarios'" class="scen">
        <div class="scen-col">
          <section class="tile">
            <div class="label">情境</div>
            <ul class="rows scen-list">
              <li v-for="item in scenarios" :key="item.id">
                <span class="scen-name">{{ item.title }}</span>
                <button class="btn small solid" :data-scenario="item.id" :disabled="scenario?.running" :title="item.description"
                        @click="runScenario(item.id)">執行</button>
              </li>
            </ul>
          </section>
          <section class="tile deep live" aria-label="模擬環境">
            <div><div class="label">市電</div><div class="big">{{ sim.grid_online ? '正常' : '中斷' }}</div></div>
            <div><div class="label">電量</div><div class="big">{{ sim.battery.toFixed(1) }}<small>%</small></div></div>
            <div><div class="label">倍速</div><div class="big">×{{ sim.speed }}</div></div>
            <div><div class="label">WOL 封包</div><div class="big">{{ sim.wol_packets }}</div></div>
          </section>
        </div>

        <div class="scen-col">
          <section v-if="scenario" class="tile tint run">
            <div class="tile-head">
              <div class="title">{{ scenario.title }}</div>
              <StatusPill :level="scenarioResult.level" :label="scenarioResult.label" size="lg" data-testid="scenario-result" />
            </div>
            <div class="run-meta">
              <span>{{ elapsed }}</span>
              <button v-if="scenario.running" class="btn small danger" data-testid="scenario-stop" @click="runScenario('cancel')">
                <Icon name="stop" :size="13" />停止
              </button>
            </div>
            <ol class="steps">
              <li v-for="(step, i) in scenario.steps" :key="i" :class="STEP_CLASS[step.status]">
                <span class="mark"><Icon v-if="STEP_ICON[step.status]" :name="STEP_ICON[step.status]" :size="14" :stroke="3" /></span>
                <div class="body">
                  <div>{{ step.label }}</div>
                  <div v-if="step.detail" class="detail">{{ cleanMessage(step.detail) }}</div>
                </div>
              </li>
            </ol>
            <div v-if="!scenario.running && scenario.detail" class="notice" :class="scenarioResult.level">
              {{ cleanMessage(scenario.detail) }}
            </div>
          </section>
          <section v-else class="tile"><div class="empty">選一個情境執行</div></section>
          <section class="tile"><FlowStepper :sequence="s.controller.sequence" /></section>
        </div>
      </div>

      <!-- 模擬器 -->
      <div v-else class="grid">
        <section class="tile accent span-4 mains" :class="{ cut: !sim.grid_online }">
          <div class="label">市電</div>
          <div class="big mains-word">{{ sim.grid_online ? '供電中' : '已切斷' }}</div>
          <svg class="mains-wave" viewBox="0 0 440 80" preserveAspectRatio="none" aria-hidden="true">
            <path :d="sim.grid_online ? WAVE.live : WAVE.flat" />
          </svg>
          <div v-if="sim.depleted" class="notice critical">電池耗盡，節點全部斷電</div>
          <button class="btn" data-testid="toggle-grid"
                  @click="simAction('grid', { value: !sim.grid_online }, sim.grid_online ? '已切斷市電' : '已恢復市電')">
            <Icon :name="sim.grid_online ? 'power' : 'plug'" :size="16" />{{ sim.grid_online ? '切斷市電' : '恢復市電' }}
          </button>
        </section>

        <section class="tile span-5 battery">
          <div class="tile-head">
            <div class="label">電量</div>
            <span class="aside">滿電可撐 {{ duration(sim.runtime, true) }}</span>
          </div>
          <div class="big">{{ batteryShown.toFixed(batteryDraft !== null ? 0 : 1) }}<small>%</small></div>
          <div class="slider">
            <input type="range" min="0" max="100" step="1" aria-label="電池電量" :value="batteryShown"
                   :style="{ '--fill': batteryShown + '%' }"
                   @input="batteryDraft = $event.target.value" @change="commitBattery" />
            <span class="th" :style="{ left: threshold + '%' }">門檻 {{ threshold }}%</span>
          </div>
        </section>

        <section class="tile span-3 speed">
          <div class="label">充放電倍速</div>
          <div class="speeds" role="group" aria-label="充放電倍速">
            <button v-for="v in SPEEDS" :key="v" :aria-pressed="sim.speed === v" @click="simAction('speed', { value: v })">×{{ v }}</button>
          </div>
        </section>

        <section class="tile span-4 link" :class="{ down: !sim.nut_reachable }">
          <div>
            <div class="label">NUT Server</div>
            <div class="link-state">{{ sim.nut_reachable ? '正常' : '已中斷' }}</div>
          </div>
          <button class="btn" :class="{ danger: sim.nut_reachable }" data-testid="toggle-nut"
                  @click="simAction('nut', { value: !sim.nut_reachable })">{{ sim.nut_reachable ? '中斷' : '恢復' }}</button>
        </section>
        <section class="tile span-4 link" :class="{ down: !sim.ptero_reachable }">
          <div>
            <div class="label">Pterodactyl 面板</div>
            <div class="link-state">{{ sim.ptero_reachable ? '正常' : '已中斷' }}</div>
          </div>
          <button class="btn" :class="{ danger: sim.ptero_reachable }" data-testid="toggle-ptero"
                  @click="simAction('ptero', { value: !sim.ptero_reachable })">{{ sim.ptero_reachable ? '中斷' : '恢復' }}</button>
        </section>

        <section class="tile span-8 agents">
          <div class="label">節點</div>
          <div class="table-wrap">
            <table class="table">
              <thead><tr><th>名稱</th><th>電源</th><th>故障</th><th class="num">關機請求</th><th class="num">WOL</th></tr></thead>
              <tbody>
                <tr v-for="agent in sim.agents" :key="agent.index" :data-sim-agent="agent.index">
                  <td class="agent-name">{{ agent.name }}</td>
                  <td>
                    <div class="power">
                      <span class="pill" :class="agent.power === 'on' ? 'good' : agent.power === 'off' ? 'neutral' : 'warning'">
                        <span class="dot"></span>{{ powerLabel(agent) }}
                      </span>
                      <button class="btn small" :data-action="isUp(agent) ? 'power-off' : 'power-on'"
                              @click="simAction('agents/' + agent.index + '/power', { power: isUp(agent) ? 'off' : 'on' })">
                        {{ isUp(agent) ? '斷電' : '開機' }}
                      </button>
                    </div>
                  </td>
                  <td>
                    <select class="select" :aria-label="agent.name + ' 故障'" :value="agent.fault"
                            @change="simAction('agents/' + agent.index + '/fault', { fault: $event.target.value })">
                      <option v-for="(label, key) in sim.agent_faults" :key="key" :value="key">{{ faultLabel(key, label) }}</option>
                    </select>
                  </td>
                  <td class="num">{{ agent.shutdown_requests }}</td>
                  <td class="num">{{ agent.wol_received }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="tile deep span-4 stuck">
          <div class="label">關不掉的伺服器</div>
          <div class="stuck-list">
            <button v-for="server in sim.servers" :key="server.identifier" :aria-pressed="server.stuck" :data-sim-server="server.identifier"
                    @click="simAction('servers/' + server.identifier + '/stuck', { value: !server.stuck })">{{ server.name }}</button>
          </div>
        </section>
      </div>
    </div>`,
}
