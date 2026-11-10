import { computed, ref } from 'vue'
import { act, agentLevel, store } from '../store.js'
import { ago, bytes, duration } from '../format.js'

const ACTIONS = [
  { id: 'status', label: '測試連線' },
  { id: 'verify', label: '驗證簽章' },
  { id: 'wol', label: '喚醒' },
]
const ACTION_LABEL = Object.fromEntries(ACTIONS.map((a) => [a.id, a.label]))
// 磚的底色跟著節點狀態走：離線變紅、預期關機變灰、開關機途中變黃
const TONE = { critical: 'down', neutral: 'off', warning: 'moving' }
const meterLevel = (pct) => (pct >= 90 ? 'critical' : pct >= 75 ? 'warning' : '')
const clamp = (pct) => Math.max(0, Math.min(100, pct))

// 一台節點（UPS_Agent）：狀態、資源用量、手動動作，模擬模式下另有故障注入
export default {
  name: 'AgentCard',
  props: {
    agent: { type: Object, required: true },
  },
  setup(props) {
    const s = computed(() => store.state)
    const expected = computed(() => s.value.controller.expected_power_state)
    const sys = computed(() => props.agent.system)
    const sim = computed(() =>
      s.value.mode === 'simulation' ? (s.value.simulation?.agents || []).find((a) => a.index === props.agent.index) : null,
    )

    const status = computed(() => {
      const agent = props.agent
      if (sim.value?.power === 'shutting_down') return { level: 'warning', label: '關機中' }
      if (sim.value?.power === 'booting') return { level: 'warning', label: '開機中' }
      // 在線時籤上直接放延遲，延遲本身就說明連得到
      if (agent.online) return { level: 'good', label: agent.latency_ms != null ? `${agent.latency_ms} ms` : '在線' }
      return agentLevel(agent, expected.value)
    })
    const tone = computed(() => TONE[status.value.level] || '')

    const meters = computed(() => {
      const sy = sys.value
      if (!sy) return []
      const list = []
      if (sy.load_avg && sy.cpu_count) {
        const pct = (sy.load_avg[0] / sy.cpu_count) * 100
        list.push({ id: 'cpu', label: 'CPU', text: `${sy.load_avg[0].toFixed(2)} / ${sy.cpu_count} 核`, pct })
      }
      if (sy.memory) {
        const used = sy.memory.total - sy.memory.available
        list.push({ id: 'mem', label: '記憶體', text: `${bytes(used)} / ${bytes(sy.memory.total)}`, pct: (used / sy.memory.total) * 100 })
      }
      if (sy.disk) {
        list.push({ id: 'disk', label: '磁碟', text: `${bytes(sy.disk.used)} / ${bytes(sy.disk.total)}`, pct: (sy.disk.used / sy.disk.total) * 100 })
      }
      return list.map((m) => ({ ...m, pct: clamp(m.pct), level: meterLevel(m.pct) }))
    })

    const uptime = computed(() => duration(sys.value?.uptime_seconds ?? props.agent.uptime_seconds, true))
    const lastSeen = computed(() => (props.agent.last_seen ? ago(props.agent.last_seen, store.now) : '從未'))
    const panelNodes = computed(() =>
      (props.agent.ptero_node_ids || []).map((id) => {
        const node = (s.value.ptero.nodes || []).find((n) => n.id === id)
        return node ? `#${id} ${node.name}` : `#${id}`
      }),
    )
    const showPanel = computed(() => s.value.ptero.configured !== false)

    const busy = ref('')
    const last = ref(null)
    async function run(action) {
      if (action === 'wol' && !sim.value && !confirm(`送出 Wake-on-LAN 到 ${props.agent.mac}？`)) return
      busy.value = action
      const result = await act(`/api/agents/${props.agent.index}/${action}`)
      busy.value = ''
      if (result) last.value = { action, ...result }
    }

    const setFault = (event) => act(`/api/sim/agents/${props.agent.index}/fault`, { fault: event.target.value }, '已套用')
    const togglePower = () => act(`/api/sim/agents/${props.agent.index}/power`, { power: sim.value.power === 'off' ? 'on' : 'off' })

    return { s, sim, status, tone, meters, uptime, lastSeen, panelNodes, showPanel, busy, last, run, setFault, togglePower, ACTIONS, ACTION_LABEL }
  },
  template: /* html */ `
    <article class="tile agent" :class="tone" :data-agent="agent.index">
      <header class="agent-head">
        <div class="agent-id">
          <h3 class="agent-name clip">{{ agent.name }}</h3>
          <div class="agent-addr clip">{{ agent.ip }}:{{ agent.port }}</div>
        </div>
        <StatusPill :level="status.level" :label="status.label" />
      </header>
      <p v-if="tone === 'down'" class="agent-error">{{ agent.error || '沒有回應' }}</p>

      <div class="agent-body">
        <div v-if="meters.length" class="meters">
          <div v-for="m in meters" :key="m.id" class="res">
            <div class="res-head"><span>{{ m.label }}</span><span class="aside">{{ m.text }}</span></div>
            <div class="meter" :class="m.level" role="meter" :aria-label="m.label" :aria-valuenow="Math.round(m.pct)"
                 aria-valuemin="0" aria-valuemax="100">
              <i :style="{ width: m.pct + '%' }"></i>
            </div>
          </div>
        </div>
        <p v-else-if="agent.online" class="aside">Agent 版本較舊，沒有系統資訊</p>

        <dl class="kv">
          <template v-if="agent.online"><dt>開機</dt><dd>{{ uptime }}</dd></template>
          <template v-else><dt>最後在線</dt><dd>{{ lastSeen }}</dd></template>
          <dt>MAC</dt>
          <dd>
            <span>{{ agent.mac || '-' }}</span>
            <span v-if="agent.mac_valid === false" class="pill critical">格式錯誤</span>
          </dd>
          <template v-if="showPanel">
            <dt>面板</dt>
            <dd>
              <template v-if="panelNodes.length">{{ panelNodes.join('、') }}</template>
              <span v-else class="pill warning">未對應</span>
            </dd>
          </template>
          <template v-if="agent.capabilities?.length">
            <dt>端點</dt>
            <dd class="caps">{{ agent.capabilities.join(' / ') }}</dd>
          </template>
        </dl>
      </div>

      <footer class="agent-actions">
        <button v-for="a in ACTIONS" :key="a.id" class="btn small" :disabled="!!busy" :data-action="a.id" @click="run(a.id)">
          <Icon v-if="busy === a.id" name="loader" :size="14" />{{ a.label }}
        </button>
      </footer>
      <div v-if="last" class="last-result" :class="last.ok ? 'good' : 'critical'" role="status">
        <b>{{ ACTION_LABEL[last.action] }}</b><span class="result-text">{{ last.detail }}</span><span class="result-ms">{{ last.elapsed_ms }} ms</span>
      </div>

      <div v-if="sim" class="sim-row">
        <span class="chip sim">模擬</span>
        <select class="select" aria-label="模擬故障" :value="sim.fault" :data-fault="agent.index" @change="setFault">
          <option v-for="(label, key) in s.simulation.agent_faults" :key="key" :value="key">{{ label }}</option>
        </select>
        <button class="btn small" data-action="sim-power" @click="togglePower">{{ sim.power === 'off' ? '開機' : '斷電' }}</button>
      </div>
    </article>`,
}
