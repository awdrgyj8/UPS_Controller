import { computed } from 'vue'
import { PHASE_LEVEL, agentLevel, powerLevel, serverStatus, store } from '../store.js'

// 版面：左欄市電與面板、中欄 UPS / NUT / Controller、右欄各節點，完整模式再往右列出遊戲伺服器。
// 電力走上緣（方框中線往上 12）、資料走下緣（往下 12），兩種線各有一條直的匯流排，全部走直角。
const BOX_W = 150
const BOX_H = 60
const NODE_W = 160
const X_LEFT = 10
const X_MID = 216
const X_NODE = 550
const X_PILL = 760
const PILL_W = 200
const PILL_H = 28
const PILL_PITCH = 34
const TOP = 34
const ROW = 90
const BUS_POWER = 466
const BUS_DATA = 506
const LANE = 12

// SVG 文字不會自動換行：中日韓字元算 2 個單位，超過就截斷
function fit(text, units) {
  let used = 0
  let out = ''
  for (const ch of String(text ?? '')) {
    used += ch.charCodeAt(0) > 0x2e80 ? 2 : 1
    if (used > units) return out + '…'
    out += ch
  }
  return out
}

function hostOf(url) {
  try {
    return new URL(url).host
  } catch {
    return url || ''
  }
}

// 系統連線拓撲圖。compact 用在總覽（不畫伺服器），完整版用在拓撲頁。
// 節點可點選，會 emit('select', id)；id 是 grid / ups / nut / controller / panel / agent-<index> / server-<identifier>。
export default {
  name: 'TopologyGraph',
  props: {
    state: { type: Object, required: true },
    compact: { type: Boolean, default: false },
    layers: { type: Object, default: () => ({ power: true, network: true, servers: true }) },
    selected: { type: String, default: '' },
  },
  emits: ['select'],
  setup(props) {
    const s = computed(() => props.state)
    const agents = computed(() => s.value.agents || [])
    const servers = computed(() => s.value.ptero?.servers || [])
    const showServers = computed(() => !props.compact && props.layers.servers)
    const simAgents = computed(() => {
      const map = {}
      for (const agent of s.value.simulation?.agents || []) map[agent.index] = agent
      return map
    })

    function agentStatus(agent) {
      const controller = s.value.controller
      const expected = controller.expected_power_state
      const sim = simAgents.value[agent.index]
      if (sim?.power === 'shutting_down') return { level: 'warning', label: '關機中' }
      if (sim?.power === 'booting') return { level: 'warning', label: '開機中' }
      if (agent.online) return { level: 'good', label: agent.latency_ms != null ? `${agent.latency_ms} ms` : '在線' }
      const seq = controller.sequence
      if (expected && seq?.kind === 'wake' && seq.result === 'success' && store.now - seq.finished_at < 300) {
        return { level: 'warning', label: '等待開機' }
      }
      return agentLevel(agent, expected)
    }

    // 左欄與中欄的固定方框
    const fixed = computed(() => {
      const st = s.value
      const ups = st.ups
      const vars = ups.variables || {}
      const nut = st.nut
      const ptero = st.ptero
      const grid = ups.ok !== true
        ? { level: 'neutral', label: '未知' }
        : ups.power ? { level: 'good', label: '' } : { level: 'critical', label: '停電' }
      const panel = ptero.configured === false
        ? { level: 'neutral', label: '未設定' }
        : ptero.ok ? { level: 'good', label: '' }
          : ptero.ok === false ? { level: 'critical', label: '無法連線' } : { level: 'neutral', label: '讀取中' }
      const nutStatus = nut.connected
        ? { level: 'good', label: '' }
        : nut.connected === false ? { level: 'critical', label: '斷線' } : { level: 'neutral', label: '連線中' }
      const power = powerLevel(ups)
      return [
        { id: 'grid', x: X_LEFT, y: TOP, title: '市電', sub: grid.label, status: grid },
        { id: 'ups', x: X_MID, y: TOP, title: vars['ups.model'] || vars['device.model'] || 'UPS', sub: power.level === 'good' ? '' : power.label, status: power },
        { id: 'nut', x: X_MID, y: TOP + ROW, title: 'NUT Server', sub: nutStatus.label || nut.host, status: nutStatus },
        {
          id: 'controller', x: X_MID, y: TOP + ROW * 2, title: 'Controller', sub: st.controller.hostname,
          status: { level: PHASE_LEVEL[st.controller.phase] || 'neutral', label: st.controller.phase_label },
        },
        { id: 'panel', x: X_LEFT, y: TOP + ROW * 2, title: 'Pterodactyl', sub: panel.label || hostOf(ptero.url), status: panel },
      ].map((box) => ({ ...box, w: BOX_W, aria: `${box.title}：${box.status.label || '正常'}` }))
    })

    // 右欄：每台節點一列；完整模式下列高跟著伺服器數量長
    const nodes = computed(() => {
      const list = []
      let y = TOP
      const push = (id, agent, title, status, hosted) => {
        const pills = showServers.value
          ? hosted.map((server, i) => ({ id: `server-${server.identifier}`, server, y: y + i * PILL_PITCH, status: serverStatus(server) }))
          : []
        const blockH = Math.max(BOX_H, pills.length * PILL_PITCH - (PILL_PITCH - PILL_H))
        const online = status.level === 'good'
        list.push({
          id, agent, title, status, pills, x: X_NODE, y, w: NODE_W, cy: y + BOX_H / 2,
          sub: props.compact && online ? '' : status.label,
          aria: `${title}：${online ? '在線' : status.label}`,
        })
        y += blockH + 30
      }
      for (const agent of agents.value) {
        push(`agent-${agent.index}`, agent, agent.name, agentStatus(agent), servers.value.filter((x) => x.agent_index === agent.index))
      }
      const unmapped = servers.value.filter((x) => x.agent_index == null)
      if (unmapped.length && showServers.value) {
        push('unmapped', null, '未對應', { level: 'neutral', label: `${unmapped.length} 台` }, unmapped)
      }
      return { list, bottom: y - 30 }
    })

    const W = computed(() => (showServers.value ? X_PILL + PILL_W + 10 : X_NODE + NODE_W + 10))
    const H = computed(() => Math.max(TOP + ROW * 2 + BOX_H, nodes.value.bottom) + 12)

    const edges = computed(() => {
      const st = s.value
      const upsOk = st.ups.ok === true
      const list = []
      const real = nodes.value.list.filter((n) => n.agent)
      const lane = (box, offset) => box.y + BOX_H / 2 + offset
      const [grid, ups, nut, controller, panel] = fixed.value

      if (props.layers.power) {
        const y = lane(ups, -LANE)
        list.push({
          id: 'grid-ups', kind: 'power', d: `M${grid.x + BOX_W} ${y}H${ups.x}`, mx: (grid.x + BOX_W + ups.x) / 2, my: y,
          state: !upsOk ? 'unknown' : st.ups.power ? 'flow' : 'broken',
        })
        const powered = real.map((n) => {
          const sim = simAgents.value[n.agent.index]
          return sim ? sim.power !== 'off' : n.agent.online
        })
        const lastY = real.length ? real[real.length - 1].cy - LANE : y
        list.push({
          id: 'ups-bus', kind: 'power', d: `M${ups.x + BOX_W} ${y}H${BUS_POWER}V${lastY}`,
          state: upsOk && powered.some(Boolean) ? 'flow' : 'idle',
        })
        real.forEach((n, i) => {
          list.push({ id: `ups-${n.id}`, kind: 'power', d: `M${BUS_POWER} ${n.cy - LANE}H${n.x}`, state: upsOk && powered[i] ? 'flow' : 'idle' })
        })
      }

      if (props.layers.network) {
        const cx = ups.x + BOX_W / 2
        const link = (connected) => (connected ? 'ok' : connected === false ? 'broken' : 'idle')
        list.push({
          id: 'ups-nut', kind: 'data', d: `M${cx} ${ups.y + BOX_H}V${nut.y}`, state: st.nut.connected ? 'ok' : 'idle',
          label: 'USB', lx: cx + 10, ly: (ups.y + BOX_H + nut.y) / 2 + 4,
        })
        list.push({
          id: 'nut-controller', kind: 'data', d: `M${cx} ${nut.y + BOX_H}V${controller.y}`, state: link(st.nut.connected),
          mx: cx, my: (nut.y + BOX_H + controller.y) / 2, label: `:${st.nut.port}`, lx: cx + 10, ly: (nut.y + BOX_H + controller.y) / 2 + 4,
        })
        const py = lane(controller, 0)
        list.push({
          id: 'controller-panel', kind: 'data', d: `M${panel.x + BOX_W} ${py}H${controller.x}`,
          state: st.ptero.configured === false ? 'idle' : link(st.ptero.ok), mx: (panel.x + BOX_W + controller.x) / 2, my: py,
        })
        if (real.length) {
          const dy = lane(controller, LANE)
          const ys = real.map((n) => n.cy + LANE)
          list.push({
            id: 'controller-bus', kind: 'data', state: 'ok',
            d: `M${controller.x + BOX_W} ${dy}H${BUS_DATA}M${BUS_DATA} ${Math.min(dy, ...ys)}V${Math.max(dy, ...ys)}`,
          })
          const expected = st.controller.expected_power_state
          real.forEach((n) => {
            list.push({
              id: `controller-${n.id}`, kind: 'data', d: `M${BUS_DATA} ${n.cy + LANE}H${n.x}`,
              state: n.agent.online ? 'ok' : expected ? 'broken' : 'idle', mx: (BUS_DATA + n.x) / 2, my: n.cy + LANE,
            })
          })
        }
      }
      return list
    })

    // 節點到它的伺服器：一條直的脊線加上各自的短橫線
    const serverLinks = computed(() => {
      const spine = X_PILL - 18
      return nodes.value.list
        .filter((n) => n.pills.length)
        .map((n) => {
          const first = n.pills[0].y + PILL_H / 2
          const last = n.pills[n.pills.length - 1].y + PILL_H / 2
          const stubs = n.pills.map((p) => `M${spine} ${p.y + PILL_H / 2}H${X_PILL}`).join('')
          return `M${n.x + n.w} ${n.cy}H${spine}M${spine} ${Math.min(first, n.cy)}V${Math.max(last, n.cy)}${stubs}`
        })
    })

    const boxes = computed(() => [...fixed.value, ...nodes.value.list])
    const pills = computed(() => nodes.value.list.flatMap((n) => n.pills))

    return { W, H, BOX_H, PILL_W, PILL_H, X_PILL, boxes, pills, edges, serverLinks, fit }
  },
  template: /* html */ `
    <div class="topo-graph">
      <svg :viewBox="'0 0 ' + W + ' ' + H" :style="{ minWidth: Math.round(W * 0.72) + 'px' }" role="img" aria-label="系統連線拓撲圖">
        <path v-for="(d, i) in serverLinks" :key="'sl' + i" class="tg-server-link" :d="d" />
        <g v-for="edge in edges" :key="edge.id" class="tg-edge" :class="[edge.kind, 's-' + edge.state]"
           :data-edge="edge.id" :data-state="edge.state">
          <path class="tg-wire" :d="edge.d" />
          <path v-if="edge.kind === 'power' && edge.state === 'flow'" class="tg-flow" :d="edge.d" />
          <text v-if="edge.label" class="tg-link-label" :x="edge.lx" :y="edge.ly">{{ edge.label }}</text>
          <g v-if="edge.state === 'broken' && edge.mx" class="tg-cut" :transform="'translate(' + edge.mx + ',' + edge.my + ')'">
            <circle r="9" /><path d="M-3.5 -3.5L3.5 3.5M3.5 -3.5L-3.5 3.5" />
          </g>
        </g>

        <g v-for="box in boxes" :key="box.id" class="tg-node" :class="[box.status.level, { selected: selected === box.id }]"
           :transform="'translate(' + box.x + ',' + box.y + ')'" tabindex="0" role="button" :aria-label="box.aria"
           :data-node="box.id" @click="$emit('select', box.id)" @keydown.enter="$emit('select', box.id)">
          <rect class="tg-box" :width="box.w" :height="BOX_H" rx="16" />
          <circle class="tg-dot" cx="22" :cy="BOX_H / 2" r="5" />
          <text class="tg-name" x="38" :y="box.sub ? 26 : 35">{{ fit(box.title, 13) }}</text>
          <text v-if="box.sub" class="tg-sub" x="38" y="45">{{ fit(box.sub, 17) }}</text>
        </g>

        <g v-for="pill in pills" :key="pill.id" class="tg-pill" :class="[pill.status.level, { selected: selected === pill.id }]"
           :transform="'translate(' + X_PILL + ',' + pill.y + ')'" tabindex="0" role="button" :data-node="pill.id"
           :aria-label="pill.server.name + '：' + pill.status.label"
           @click="$emit('select', pill.id)" @keydown.enter="$emit('select', pill.id)">
          <rect class="tg-box" :width="PILL_W" :height="PILL_H" rx="14" />
          <circle class="tg-dot" cx="15" :cy="PILL_H / 2" r="4" />
          <text class="tg-pill-name" x="27" :y="PILL_H / 2 + 4.5">{{ fit(pill.server.name, pill.status.level === 'good' ? 20 : 13) }}</text>
          <text v-if="pill.status.level !== 'good'" class="tg-sub" :x="PILL_W - 12" :y="PILL_H / 2 + 4.5" text-anchor="end">{{ pill.status.label }}</text>
        </g>
      </svg>
    </div>`,
}
