import { computed } from 'vue'
import TopologyGraph from '../components/topology-graph.js'
import { agentLevel, isServerRunning, serverStatus, store } from '../store.js'
import { clock, duration, num } from '../format.js'

// 電池液面的波形：週期 120，畫得比電池寬，靠位移做出流動
function wavePath(amp, phase) {
  let d = `M${-240 + phase} 0`
  for (let x = -240 + phase; x < 420; x += 120) d += `q30 ${-amp} 60 0t60 0`
  return d + 'V420H-240Z'
}
// 市電的正弦波；停電時畫成一條平線
function sinePath(flat) {
  let d = ''
  for (let x = -4; x <= 444; x += 4) d += `${d ? 'L' : 'M'}${x} ${(46 + (flat ? 0 : Math.sin((x / 440) * Math.PI * 8) * 24)).toFixed(1)}`
  return d
}
const CELL = { top: 30, bottom: 396 } // 電池內部可填滿的範圍（SVG 座標）
const GAUGE_ARC = 405.3 // 負載弧（270 度）的長度

export default {
  name: 'OverviewView',
  components: { TopologyGraph },
  setup() {
    const s = computed(() => store.state)
    const ups = computed(() => s.value.ups)
    const vars = computed(() => ups.value.variables || {})
    const upsOk = computed(() => ups.value.ok === true)
    const threshold = computed(() => s.value.settings.shutdown_battery_threshold)
    const expected = computed(() => s.value.controller.expected_power_state)

    // ---- 電池 ----
    const model = computed(() => vars.value['ups.model'] || vars.value['device.model'] || '')
    const chargeState = computed(() => {
      if (!upsOk.value) return ''
      const flags = (ups.value.status_flags || []).map((f) => f.code)
      if (flags.includes('DISCHRG') || ups.value.power === false) return '放電中'
      if (flags.includes('CHRG')) return '充電中'
      return ups.value.battery >= 100 ? '已充飽' : ''
    })
    const cellY = (pct) => CELL.bottom - (CELL.bottom - CELL.top) * (Math.min(100, Math.max(0, pct)) / 100)
    // 滿格時在頂端留一點空間，波浪才看得到
    const levelY = computed(() => cellY((ups.value.battery ?? 0) * 0.955))
    const thresholdY = computed(() => cellY(threshold.value))

    // ---- 負載 ----
    const loadLevel = computed(() => (ups.value.load >= 90 ? 'critical' : ups.value.load >= 75 ? 'warning' : ''))
    const gaugeDash = computed(() => `${(GAUGE_ARC * Math.min(100, ups.value.load ?? 0)) / 100} 540.4`)
    const watts = computed(() => vars.value['ups.realpower'])
    const wattsMax = computed(() => vars.value['ups.realpower.nominal'])

    // ---- 市電 ----
    const mainsDown = computed(() => upsOk.value && ups.value.power === false)
    const sine = computed(() => sinePath(!upsOk.value || mainsDown.value))

    // ---- 節點 ----
    const agents = computed(() => s.value.agents || [])
    const servers = computed(() => s.value.ptero.servers || [])
    const online = computed(() => agents.value.filter((a) => a.online).length)
    const running = computed(() => servers.value.filter(isServerRunning).length)
    const nodeTiles = computed(() => {
      const tiles = agents.value.map((agent) => ({
        key: `agent-${agent.index}`,
        name: agent.name,
        ip: agent.ip,
        status: agent.online
          ? { level: 'good', label: agent.latency_ms != null ? `${agent.latency_ms} ms` : '在線' }
          : agentLevel(agent, expected.value),
        servers: servers.value.filter((x) => x.agent_index === agent.index),
      }))
      const unmapped = servers.value.filter((x) => x.agent_index == null)
      if (unmapped.length) tiles.push({ key: 'unmapped', name: '未對應', ip: '', status: null, servers: unmapped })
      return tiles
    })

    // ---- 自動關機 / 喚醒條件：與控制器的判斷相同 ----
    const conditions = computed(() => {
      const u = ups.value
      if (expected.value !== false) {
        return [
          { label: '節點應開機', ok: true },
          { label: 'UPS 可讀取', ok: upsOk.value },
          { label: '電池供電', ok: upsOk.value && u.power === false },
          { label: `電量 ≤ ${threshold.value}%`, ok: u.battery != null && u.battery <= threshold.value },
        ]
      }
      return [
        { label: '節點應關機', ok: true },
        { label: 'UPS 可讀取', ok: upsOk.value },
        { label: '市電恢復', ok: upsOk.value && u.power === true },
      ]
    })
    const waking = computed(() => expected.value === false)
    const verdict = computed(() => {
      const unmet = conditions.value.filter((c) => !c.ok)
      if (s.value.controller.paused) return '已暫停'
      if (waking.value) return unmet.length ? '等市電恢復' : '即將喚醒'
      if (!unmet.length) return '開始關機'
      return unmet.length === 1 && unmet[0] === conditions.value[3] ? '只差電量' : '不會關機'
    })

    // ---- 趨勢、事件 ----
    const series = (key) => store.history.map((sample) => ({ t: sample.t, v: sample[key] }))
    const batterySeries = computed(() => series('battery'))
    const loadSeries = computed(() => [{ samples: series('load'), color: 'var(--ink-3)' }])
    // 顯示範圍跟著已有的資料長，最多一小時，剛啟動時才不會只有右邊一小條
    const windowSec = computed(() => {
      const first = store.history[0]?.t
      const span = first ? store.now - first : 0
      return Math.min(3600, Math.max(300, Math.ceil(span / 300) * 300))
    })
    const events = computed(() => [...(s.value.events || [])].reverse().slice(0, 4))

    function openNode(id) {
      location.hash = `#/topology?node=${id}`
    }

    return {
      store, s, ups, upsOk, threshold, model, chargeState, levelY, thresholdY, loadLevel, gaugeDash, watts, wattsMax,
      mainsDown, sine, agents, servers, online, running, nodeTiles, conditions, waking, verdict,
      batterySeries, loadSeries, windowSec, events, openNode, isServerRunning, serverStatus, duration, num, clock,
      waveFront: wavePath(7, 0), waveBack: wavePath(9, 45),
    }
  },
  template: /* html */ `
    <main class="v-overview grid">
      <!-- 電池 -->
      <section class="tile accent hero" aria-label="電池">
        <div class="hero-copy">
          <div class="label">電量</div>
          <div class="hero-num" data-testid="battery">{{ ups.battery ?? '–' }}<small>%</small></div>
          <div v-if="upsOk && ups.runtime != null" class="hero-run">可撐 {{ duration(ups.runtime) }}</div>
          <div class="hero-foot">
            <span v-if="model">{{ model }}</span>
            <span v-if="chargeState">{{ chargeState }}</span>
          </div>
        </div>
        <svg class="cell" viewBox="0 0 172 408" aria-hidden="true">
          <defs><clipPath id="cell-clip"><rect x="12" y="30" width="148" height="366" rx="34" /></clipPath></defs>
          <rect class="cell-cap" x="58" y="0" width="56" height="16" rx="7" />
          <rect class="cell-glass" x="4" y="22" width="164" height="382" rx="42" />
          <g clip-path="url(#cell-clip)">
            <g class="cell-level" :style="{ transform: 'translateY(' + levelY + 'px)' }">
              <path class="cell-wave-back" :d="waveBack" />
              <path class="cell-wave" :d="waveFront" />
            </g>
          </g>
          <g :transform="'translate(0,' + thresholdY + ')'">
            <path class="cell-th-line" d="M14 0H158" />
            <rect class="cell-th-pill" x="34" y="-15" width="104" height="30" rx="15" />
            <text class="cell-th-text" x="86" y="5" text-anchor="middle">{{ threshold }}% 關機</text>
          </g>
        </svg>
      </section>

      <!-- 負載 -->
      <section class="tile load" :class="loadLevel" aria-label="負載">
        <div class="label">負載</div>
        <svg class="gauge" viewBox="0 0 220 200" role="img" aria-label="負載百分比">
          <defs>
            <linearGradient id="g-accent" x1="0" y1="1" x2="1" y2="0">
              <stop offset="0" stop-color="var(--a1)" /><stop offset="1" stop-color="var(--a2)" />
            </linearGradient>
          </defs>
          <circle class="gauge-track" cx="110" cy="112" r="86" stroke-dasharray="405.3 540.4" transform="rotate(135 110 112)" />
          <circle class="gauge-value" cx="110" cy="112" r="86" :stroke-dasharray="gaugeDash" transform="rotate(135 110 112)" />
          <text x="110" y="134" text-anchor="middle"><tspan class="g-num">{{ ups.load ?? '–' }}</tspan><tspan class="g-unit" dx="4">%</tspan></text>
        </svg>
        <div v-if="watts" class="load-w">
          <span class="big">{{ watts }}<small>W</small></span>
          <span v-if="wattsMax" class="aside">/ {{ wattsMax }} W</span>
        </div>
      </section>

      <!-- 市電 -->
      <section class="tile tint mains" :class="{ down: mainsDown }" aria-label="市電">
        <div class="label">市電</div>
        <div class="mains-row">
          <template v-if="mainsDown">
            <div class="big">停電</div>
            <div v-if="ups.on_battery_since" class="hz">{{ clock(ups.on_battery_since) }} 起</div>
          </template>
          <template v-else>
            <div class="big">{{ upsOk ? num(ups.input_voltage, 1) : '–' }}<small>V</small></div>
            <div v-if="upsOk && ups.input_frequency != null" class="hz">{{ num(ups.input_frequency, 2) }} Hz</div>
          </template>
        </div>
        <svg class="mains-wave" viewBox="0 0 440 86" preserveAspectRatio="none" aria-hidden="true"><path :d="sine" /></svg>
      </section>

      <section class="tile mini out" :class="{ wide: ups.temperature == null }" aria-label="輸出電壓">
        <div class="label">輸出</div>
        <div class="big">{{ upsOk ? num(ups.output_voltage, 1) : '–' }}<small>V</small></div>
      </section>
      <section v-if="ups.temperature != null" class="tile mini temp" aria-label="UPS 溫度">
        <div class="label">溫度</div>
        <div class="big">{{ num(ups.temperature, 1) }}<small>°C</small></div>
      </section>

      <!-- 節點 -->
      <section class="tile lime count" aria-label="在線數">
        <div class="label">節點在線</div>
        <div class="big" data-testid="nodes-online">{{ online }}<em>/{{ agents.length }}</em></div>
        <div class="count-row">
          <span>伺服器 {{ running }}/{{ servers.length }}</span>
          <span class="pips" aria-hidden="true"><i v-for="x in servers" :key="x.identifier" :class="{ off: !isServerRunning(x) }"></i></span>
        </div>
      </section>
      <div class="nodes">
        <section v-for="node in nodeTiles" :key="node.key" class="tile node" :data-tile="node.key">
          <div class="node-head">
            <div class="clip">
              <a class="node-name" :href="'#/topology?node=' + node.key">{{ node.name }}</a>
              <div v-if="node.ip" class="node-ip">{{ node.ip }}</div>
            </div>
            <StatusPill v-if="node.status" :level="node.status.level" :label="node.status.label" />
          </div>
          <ul class="rows">
            <li v-for="x in node.servers" :key="x.identifier" :class="serverStatus(x).level">
              <span class="dot"></span><span class="clip">{{ x.name }}</span>
              <span v-if="!isServerRunning(x)" class="row-end">{{ serverStatus(x).label }}</span>
            </li>
          </ul>
        </section>
      </div>

      <!-- 拓撲 -->
      <section class="tile deep topo" aria-label="電力與連線">
        <div class="tile-head">
          <a class="label" href="#/topology">電力與連線</a>
          <div class="legend"><span><i></i>電力</span><span><i class="data"></i>資料</span></div>
        </div>
        <TopologyGraph :state="s" compact @select="openNode" />
      </section>

      <!-- 關機條件 -->
      <section class="tile tint conds" aria-label="關機條件">
        <div class="label">{{ waking ? '喚醒條件' : '關機條件' }}</div>
        <div class="verdict" data-testid="verdict">{{ verdict }}</div>
        <div class="segs" aria-hidden="true"><i v-for="c in conditions" :key="c.label" :class="{ met: c.ok }"></i></div>
        <ul class="cond-list">
          <li v-for="c in conditions" :key="c.label" :class="{ met: c.ok }"><span>{{ c.label }}</span><b>{{ c.ok ? '是' : '否' }}</b></li>
        </ul>
      </section>

      <!-- 趨勢 -->
      <section class="tile trend" aria-label="趨勢">
        <div class="tile-head">
          <div class="label">趨勢</div>
          <div class="keys"><span><i></i>電量</span><span><i class="load-key"></i>負載</span></div>
        </div>
        <LineChart :samples="batterySeries" :extra="loadSeries" :now="store.now" :window-sec="windowSec" :min="0" :max="100"
                   unit="%" :height="230" label="電量與負載趨勢" :threshold="{ value: threshold, label: '門檻' }" />
      </section>

      <!-- 流程 -->
      <section class="tile flow-tile" aria-label="控制流程">
        <FlowStepper :sequence="s.controller.sequence" />
      </section>

      <!-- 事件 -->
      <section class="tile events" aria-label="最近事件">
        <div class="tile-head"><div class="label">最近事件</div><a class="btn small" href="#/logs">全部</a></div>
        <EventList :events="events" />
      </section>
    </main>`,
}
