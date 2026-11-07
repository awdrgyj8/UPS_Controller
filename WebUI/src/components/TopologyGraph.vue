<script setup>
import { computed } from 'vue'
import Icon from './Icon.vue'
import { PHASE_LEVEL, agentLevel, isServerRunning, powerLevel, serverStatus, store, wattsText } from '../store.js'

const props = defineProps({
  state: { type: Object, required: true },
  compact: { type: Boolean, default: false },
  layers: { type: Object, default: () => ({ power: true, network: true, servers: true }) },
  selected: { type: String, default: '' },
})
const emit = defineEmits(['select'])

const NODE_W = 176
const NODE_H = 78
const ROW_0 = 16
const ROW_1 = 136
const PILL_H = 24
const PILL_GAP = 6

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

const s = computed(() => props.state)
const agents = computed(() => s.value.agents || [])
const servers = computed(() => s.value.ptero?.servers || [])
const unmapped = computed(() => servers.value.filter((server) => server.agent_index == null))
const simAgents = computed(() => {
  const map = {}
  for (const agent of s.value.simulation?.agents || []) map[agent.index] = agent
  return map
})
const columns = computed(() => agents.value.length + (unmapped.value.length && !props.compact ? 1 : 0))
const W = computed(() => Math.max(800, columns.value * (NODE_W + 44) + 60))
const ROW_B = computed(() => 306)
const ROW_C = computed(() => ROW_B.value + NODE_H + 28)
const maxServers = computed(() => {
  let max = unmapped.value.length
  for (const agent of agents.value) max = Math.max(max, (agent.servers || []).length)
  return max
})
const H = computed(() => {
  if (props.compact || !props.layers.servers || !maxServers.value) return ROW_B.value + NODE_H + 16
  return ROW_C.value + maxServers.value * (PILL_H + PILL_GAP) + 10
})

function hostOf(url) {
  try {
    return new URL(url).host
  } catch {
    return url || '-'
  }
}

function agentStatus(agent) {
  const controller = s.value.controller
  const expected = controller.expected_power_state
  const sim = simAgents.value[agent.index]
  if (sim?.power === 'shutting_down') return { level: 'warning', label: '關機中…' }
  if (sim?.power === 'booting') return { level: 'warning', label: '開機中…' }
  if (agent.online) return { level: 'good', label: `在線 · ${agent.latency_ms ?? '-'} ms` }
  const seq = controller.sequence
  if (expected && seq?.kind === 'wake' && seq.result === 'success' && store.now - seq.finished_at < 300) {
    return { level: 'warning', label: '等待開機…' }
  }
  return agentLevel(agent, expected)
}

const topNodes = computed(() => {
  const st = s.value
  const ups = st.ups
  const vars = ups.variables || {}
  const nut = st.nut
  const ptero = st.ptero
  const left = 40
  const middle = W.value / 2 - NODE_W / 2
  const right = W.value - 40 - NODE_W
  const gridStatus = ups.ok !== true
    ? { level: 'neutral', label: '未知' }
    : ups.power
      ? { level: 'good', label: '供電正常' }
      : { level: 'critical', label: '停電' }
  const panelStatus = ptero.configured === false
    ? { level: 'neutral', label: '未設定' }
    : ptero.ok
      ? { level: 'good', label: `${ptero.servers.length} 台伺服器` }
      : ptero.ok === false
        ? { level: 'critical', label: '無法連線' }
        : { level: 'neutral', label: '讀取中' }
  return [
    {
      id: 'grid', x: left, y: ROW_0, icon: 'plug', title: '市電',
      sub: ups.ok && ups.power ? `${vars['input.voltage'] ?? '-'} V · ${vars['input.frequency'] ?? '-'} Hz` : '無輸入',
      status: gridStatus,
    },
    {
      id: 'ups', x: left, y: ROW_1, icon: 'battery', title: vars['ups.model'] || vars['device.model'] || 'UPS',
      sub: ups.ok
        ? `電量 ${ups.battery ?? '-'}% · ${ups.realpower != null ? wattsText(ups) : `負載 ${ups.load ?? '-'}%`}`
        : '無資料',
      status: powerLevel(ups),
    },
    {
      id: 'nut', x: middle, y: ROW_0, icon: 'database', title: 'NUT Server', sub: `${nut.host}:${nut.port}`,
      status: nut.connected ? { level: 'good', label: `已連線 · ${nut.latency_ms} ms` }
        : nut.connected === false ? { level: 'critical', label: '斷線' } : { level: 'neutral', label: '連線中' },
    },
    {
      id: 'controller', x: middle, y: ROW_1, icon: 'cpu', title: 'Controller', sub: st.controller.hostname,
      status: { level: PHASE_LEVEL[st.controller.phase] || 'neutral', label: st.controller.phase_label },
    },
    { id: 'panel', x: right, y: ROW_1, icon: 'panel', title: 'Pterodactyl', sub: hostOf(ptero.url), status: panelStatus },
  ]
})

const agentNodes = computed(() => {
  const n = columns.value || 1
  const nodes = agents.value.map((agent, i) => {
    const hosted = servers.value.filter((server) => server.agent_index === agent.index)
    const running = hosted.filter(isServerRunning).length
    return {
      id: `agent-${agent.index}`,
      agent,
      x: (W.value * (i + 0.5)) / n - NODE_W / 2,
      y: ROW_B.value,
      icon: 'server',
      title: agent.name,
      sub: props.compact ? `${hosted.length} 台伺服器 · ${running} 運行` : `${agent.ip}:${agent.port}`,
      status: agentStatus(agent),
      servers: hosted,
    }
  })
  if (unmapped.value.length && !props.compact) {
    nodes.push({
      id: 'unmapped', agent: null, x: (W.value * (n - 0.5)) / n - NODE_W / 2, y: ROW_B.value, icon: 'game',
      title: '未對應的伺服器', sub: '找不到所屬 Agent', status: { level: 'neutral', label: `${unmapped.value.length} 台` },
      servers: unmapped.value,
    })
  }
  return nodes
})

const nodeById = computed(() => {
  const map = {}
  for (const node of [...topNodes.value, ...agentNodes.value]) map[node.id] = node
  return map
})

function horizontal(a, b) {
  const y = a.y + NODE_H / 2
  return { d: `M${a.x + NODE_W},${y} L${b.x},${y}`, mx: (a.x + NODE_W + b.x) / 2, my: y - 8 }
}

function vertical(a, b) {
  const x = a.x + NODE_W / 2
  return { d: `M${x},${a.y + NODE_H} L${x},${b.y}`, mx: x + 8, my: (a.y + NODE_H + b.y) / 2 + 4, anchor: 'start' }
}

// 由左下節點的右側連到右上節點的左側
function diagonal(a, b) {
  const x1 = a.x + NODE_W
  const y1 = a.y + NODE_H / 2
  const x2 = b.x
  const y2 = b.y + NODE_H / 2
  const dx = (x2 - x1) / 2
  return { d: `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`, mx: (x1 + x2) / 2, my: (y1 + y2) / 2 - 8 }
}

function downward(a, b, offset) {
  const x1 = a.x + NODE_W / 2 + offset / 3
  const y1 = a.y + NODE_H
  const x2 = b.x + NODE_W / 2 + offset
  const y2 = b.y
  const dy = (y2 - y1) / 2
  return { d: `M${x1},${y1} C${x1},${y1 + dy} ${x2},${y2 - dy} ${x2},${y2}`, mx: (x1 + x2) / 2, my: (y1 + y2) / 2 }
}

const edges = computed(() => {
  const st = s.value
  const n = nodeById.value
  const list = []
  const upsOk = st.ups.ok === true
  // 電力
  if (props.layers.power) {
    list.push({
      id: 'grid-ups', kind: 'power', ...vertical(n.grid, n.ups),
      state: !upsOk ? 'unknown' : st.ups.power ? 'flow' : 'broken',
      label: !upsOk ? '' : st.ups.power ? 'AC 輸入' : '市電中斷',
    })
    for (const node of agentNodes.value) {
      if (!node.agent) continue
      const sim = simAgents.value[node.agent.index]
      const powered = sim ? sim.power !== 'off' : node.agent.online
      list.push({ id: `ups-${node.id}`, kind: 'power', ...downward(n.ups, node, -38), state: powered ? 'flow' : 'idle' })
    }
  }
  // 網路
  if (props.layers.network) {
    list.push({ id: 'ups-nut', kind: 'network', ...diagonal(n.ups, n.nut), state: st.nut.connected ? 'ok' : 'idle', label: 'USB / SNMP' })
    list.push({
      id: 'nut-controller', kind: 'network', ...vertical(n.nut, n.controller),
      state: st.nut.connected ? 'ok' : st.nut.connected === false ? 'broken' : 'idle', label: `NUT :${st.nut.port}`,
    })
    list.push({
      id: 'controller-panel', kind: 'network', ...horizontal(n.controller, n.panel),
      state: st.ptero.ok ? 'ok' : st.ptero.ok === false ? 'broken' : 'idle', label: 'HTTPS API',
    })
    const expected = st.controller.expected_power_state
    for (const node of agentNodes.value) {
      if (!node.agent) continue
      const online = node.agent.online
      list.push({
        id: `controller-${node.id}`, kind: 'network', ...downward(n.controller, node, 38),
        state: online ? 'ok' : expected ? 'broken' : 'idle',
        label: props.compact ? '' : online ? `HTTP · ${node.agent.latency_ms} ms` : expected ? '無回應' : 'WOL 待命',
      })
    }
  }
  return list
})

const pills = computed(() => {
  if (props.compact || !props.layers.servers) return []
  const list = []
  for (const node of agentNodes.value) {
    node.servers.forEach((server, i) => {
      list.push({
        id: `server-${server.identifier}`,
        server,
        x: node.x,
        y: ROW_C.value + i * (PILL_H + PILL_GAP),
        status: serverStatus(server),
        parentX: node.x + 14,
        parentY: node.y + NODE_H,
      })
    })
  }
  return list
})

function select(id) {
  emit('select', id)
}
</script>

<template>
  <div class="topology">
    <svg :viewBox="`0 0 ${W} ${H}`" :style="{ minWidth: Math.round(W * 0.72) + 'px' }" role="img"
         aria-label="系統連線拓撲圖">
      <!-- 連線 -->
      <g class="edges">
        <g v-for="edge in edges" :key="edge.id" :class="['edge', edge.kind, `s-${edge.state}`]" :data-edge="edge.id" :data-state="edge.state">
          <path :d="edge.d" class="base" />
          <path v-if="edge.state === 'flow'" :d="edge.d" class="flow-overlay" />
          <g v-if="edge.state === 'broken'" :transform="`translate(${edge.anchor ? edge.mx - 8 : edge.mx},${edge.anchor ? edge.my - 4 : edge.my + 8})`" class="cut">
            <circle r="9" />
            <path d="M-3.5,-3.5 L3.5,3.5 M3.5,-3.5 L-3.5,3.5" />
          </g>
          <text v-if="edge.label" :x="edge.anchor && edge.state === 'broken' ? edge.mx + 8 : edge.mx"
                :y="edge.state === 'broken' && !edge.anchor ? edge.my - 8 : edge.my"
                :text-anchor="edge.anchor || 'middle'" class="edge-label">{{ edge.label }}</text>
        </g>
        <!-- 伺服器掛在節點下 -->
        <path v-for="pill in pills" :key="'c' + pill.id" class="server-link"
              :d="`M${pill.parentX},${pill.parentY} L${pill.parentX},${pill.y + PILL_H / 2} L${pill.x + 22},${pill.y + PILL_H / 2}`" />
      </g>

      <!-- 節點 -->
      <g v-for="node in [...topNodes, ...agentNodes]" :key="node.id" class="node"
         :class="[node.status.level, { selected: selected === node.id }]"
         :transform="`translate(${node.x},${node.y})`" tabindex="0" role="button" :aria-label="`${node.title}：${node.status.label}`"
         :data-node="node.id" @click="select(node.id)" @keydown.enter="select(node.id)">
        <rect :width="NODE_W" :height="NODE_H" rx="12" class="box" />
        <rect x="0" y="14" width="3" :height="NODE_H - 28" rx="1.5" class="stripe" />
        <circle cx="28" cy="27" r="16" class="icon-bg" />
        <g transform="translate(19,18)" class="icon"><Icon :name="node.icon" :size="18" /></g>
        <text x="52" y="24" class="title">{{ fit(node.title, 15) }}</text>
        <text x="52" y="42" class="sub">{{ fit(node.sub, compact && node.agent ? 22 : 19) }}</text>
        <circle cx="56" cy="60" r="8.5" class="halo" />
        <circle cx="56" cy="60" r="4.5" class="sdot" />
        <text x="66" y="64" class="stext">{{ fit(node.status.label, 17) }}</text>
      </g>

      <!-- 遊戲伺服器 -->
      <g v-for="pill in pills" :key="pill.id" class="pill" :class="[pill.status.level, { selected: selected === pill.id }]"
         :transform="`translate(${pill.x + 22},${pill.y})`" tabindex="0" role="button" :data-node="pill.id"
         :aria-label="`${pill.server.name}：${pill.status.label}`" @click="select(pill.id)" @keydown.enter="select(pill.id)">
        <rect :width="NODE_W - 22" :height="PILL_H" rx="12" class="pill-box" />
        <circle cx="13" :cy="PILL_H / 2" r="7.5" class="halo" />
        <circle cx="13" :cy="PILL_H / 2" r="4" class="sdot" />
        <text x="23" :y="PILL_H / 2 + 4" class="pill-name">{{ fit(pill.server.name, 13) }}</text>
        <text :x="NODE_W - 30" :y="PILL_H / 2 + 4" text-anchor="end" class="pill-state">{{ pill.status.label }}</text>
      </g>
    </svg>
  </div>
</template>

<style scoped>
.topology {
  overflow-x: auto;
}
svg {
  width: 100%;
  height: auto;
  display: block;
}
.node {
  cursor: pointer;
  --c: var(--neutral);
}
.node:focus {
  outline: none;
}
.box {
  fill: var(--surface-2);
  stroke: var(--border-strong);
  stroke-width: 1;
}
.node:hover .box {
  fill: var(--surface-3);
}
.node.selected .box,
.node:focus-visible .box {
  stroke: var(--accent);
  stroke-width: 2;
}
.stripe,
.sdot {
  fill: var(--c);
}
.icon-bg {
  fill: color-mix(in srgb, var(--c) 18%, var(--surface));
}
.icon {
  color: var(--text);
}
.title {
  font-size: 13px;
  font-weight: 600;
  fill: var(--text);
}
.sub {
  font-size: 11.5px;
  fill: var(--text-2);
}
.stext {
  font-size: 11.5px;
  fill: var(--text);
  font-weight: 500;
}
.halo {
  fill: var(--c);
  opacity: 0.28;
}
.neutral .halo {
  opacity: 0;
}
.warning .halo {
  animation: pulse 1.6s ease-in-out infinite;
}
@keyframes pulse {
  50% { opacity: 0.05; }
}
@media (prefers-reduced-motion: reduce) {
  .warning .halo { animation: none; }
}
.good { --c: var(--good); }
.warning { --c: var(--warning); }
.serious { --c: var(--serious); }
.critical { --c: var(--critical); }
.neutral { --c: var(--neutral); }

/* 連線 */
.edge .base {
  fill: none;
  stroke-width: 2;
}
.edge.power .base {
  stroke: var(--power);
}
.edge.network .base {
  stroke: var(--network);
  stroke-width: 1.5;
}
.edge.s-idle .base {
  stroke: var(--axis);
  stroke-dasharray: 3 5;
}
.edge.s-broken .base {
  stroke: var(--critical);
  stroke-dasharray: 6 5;
}
.edge.s-unknown .base {
  stroke: var(--axis);
}
.flow-overlay {
  fill: none;
  stroke: color-mix(in srgb, var(--power) 35%, #fff);
  stroke-width: 2;
  stroke-dasharray: 4 14;
  animation: dash 1.1s linear infinite;
}
@keyframes dash {
  from { stroke-dashoffset: 18; }
  to { stroke-dashoffset: 0; }
}
.cut circle {
  fill: var(--critical);
  stroke: var(--surface);
  stroke-width: 2;
}
.cut path {
  stroke: #fff;
  stroke-width: 2;
  stroke-linecap: round;
}
.edge-label {
  font-size: 11px;
  fill: var(--text-2);
  paint-order: stroke;
  stroke: var(--surface);
  stroke-width: 4px;
  stroke-linejoin: round;
}
.server-link {
  fill: none;
  stroke: var(--axis);
  stroke-width: 1;
}

/* 伺服器 */
.pill {
  cursor: pointer;
}
.pill:focus {
  outline: none;
}
.pill-box {
  fill: var(--surface-2);
  stroke: var(--border);
}
.pill:hover .pill-box {
  fill: var(--surface-3);
}
.pill.selected .pill-box,
.pill:focus-visible .pill-box {
  stroke: var(--accent);
  stroke-width: 2;
}
.pill-name {
  font-size: 11.5px;
  fill: var(--text);
}
.pill-state {
  font-size: 10.5px;
  fill: var(--text-2);
}
</style>
