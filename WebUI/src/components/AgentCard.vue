<script setup>
import { computed, ref } from 'vue'
import Icon from './Icon.vue'
import Meter from './Meter.vue'
import StatusPill from './StatusPill.vue'
import { act, agentLevel, serverLevel, store } from '../store.js'
import { ago, bytes, duration } from '../format.js'

const props = defineProps({
  agent: { type: Object, required: true },
  flat: { type: Boolean, default: false },
})

const s = computed(() => store.state)
const expected = computed(() => s.value.controller.expected_power_state)
const status = computed(() => agentLevel(props.agent, expected.value))
const sys = computed(() => props.agent.system)
const servers = computed(() => (s.value.ptero.servers || []).filter((server) => server.agent_index === props.agent.index))
const sim = computed(() => (s.value.simulation?.agents || []).find((agent) => agent.index === props.agent.index))
const isSim = computed(() => s.value.mode === 'simulation')
const mismatch = computed(() => expected.value === true && !props.agent.online && sim.value?.power !== 'booting')

const memUsed = computed(() => (sys.value?.memory ? sys.value.memory.total - sys.value.memory.available : null))
const memPct = computed(() => (sys.value?.memory ? (memUsed.value / sys.value.memory.total) * 100 : null))
const diskPct = computed(() => (sys.value?.disk ? (sys.value.disk.used / sys.value.disk.total) * 100 : null))
const loadPct = computed(() => (sys.value?.load_avg && sys.value.cpu_count ? (sys.value.load_avg[0] / sys.value.cpu_count) * 100 : null))

const busy = ref('')
const last = ref(null)
const LABELS = { status: '連線測試', verify: '簽章驗證', wol: 'Wake-on-LAN' }

async function run(action) {
  if (action === 'wol' && !isSim.value && !confirm(`確定要送出 Wake-on-LAN 封包到 ${props.agent.mac}？`)) return
  busy.value = action
  const result = await act(`/api/agents/${props.agent.index}/${action}`)
  busy.value = ''
  if (result) last.value = { action, ...result }
}

async function setFault(event) {
  await act(`/api/sim/agents/${props.agent.index}/fault`, { fault: event.target.value }, '已套用故障設定')
}

async function setPower(power) {
  await act(`/api/sim/agents/${props.agent.index}/power`, { power })
}

const meterLevel = (pct) => (pct === null ? 'neutral' : pct >= 90 ? 'critical' : pct >= 75 ? 'warning' : 'accent')
</script>

<template>
  <article class="agent" :class="{ card: !flat }" :data-agent="agent.index">
    <header>
      <div class="avatar" :class="status.level"><Icon name="server" :size="18" /></div>
      <div class="titles">
        <h3>{{ agent.name }}</h3>
        <div class="mono muted">{{ agent.ip }}:{{ agent.port }}</div>
      </div>
      <StatusPill :level="status.level" :label="status.label" />
    </header>

    <div v-if="mismatch" class="notice critical">
      <Icon name="alert" :size="16" />
      <span>預期為開機，但 Agent 無回應：{{ agent.error || '無法連線' }}</span>
    </div>

    <dl class="kv">
      <dt>Hostname</dt><dd>{{ agent.hostname || '-' }}</dd>
      <dt>MAC</dt>
      <dd class="mono">
        {{ agent.mac || '-' }}
        <span v-if="agent.mac_valid === false" class="chip warn-chip">格式錯誤</span>
      </dd>
      <dt>延遲</dt><dd class="tabular">{{ agent.latency_ms != null ? agent.latency_ms + ' ms' : '-' }}</dd>
      <dt>Agent 執行</dt><dd>{{ duration(agent.uptime_seconds, true) }}</dd>
      <dt>系統開機</dt><dd>{{ duration(sys?.uptime_seconds, true) }}</dd>
      <dt>最後在線</dt><dd>{{ agent.online ? '現在' : ago(agent.last_seen, store.now) }}</dd>
      <template v-if="sys">
        <dt>平台</dt><dd class="platform" :title="sys.platform">{{ sys.platform || '-' }}</dd>
      </template>
      <template v-if="agent.ptero_node_id != null">
        <dt>面板 node</dt><dd>#{{ agent.ptero_node_id }}</dd>
      </template>
    </dl>

    <div v-if="sys" class="resources">
      <div v-if="loadPct !== null">
        <div class="res-label"><span>CPU 負載（{{ sys.cpu_count }} 核）</span><span class="tabular">{{ sys.load_avg.join(' / ') }}</span></div>
        <Meter :value="loadPct" :level="meterLevel(loadPct)" />
      </div>
      <div v-if="memPct !== null">
        <div class="res-label"><span>記憶體</span><span class="tabular">{{ bytes(memUsed) }} / {{ bytes(sys.memory.total) }}</span></div>
        <Meter :value="memPct" :level="meterLevel(memPct)" />
      </div>
      <div v-if="diskPct !== null">
        <div class="res-label"><span>磁碟 /</span><span class="tabular">{{ bytes(sys.disk.used) }} / {{ bytes(sys.disk.total) }}</span></div>
        <Meter :value="diskPct" :level="meterLevel(diskPct)" />
      </div>
    </div>
    <div v-else-if="agent.online" class="muted small">此 Agent 版本較舊，未回報系統資訊（更新 UPS_Agent 後可顯示 CPU / 記憶體 / 磁碟）</div>

    <div v-if="agent.capabilities?.length" class="caps">
      <span v-for="cap in agent.capabilities" :key="cap" class="chip mono">/{{ cap }}</span>
    </div>

    <div v-if="servers.length" class="servers">
      <h4 class="section-title">遊戲伺服器（{{ servers.length }}）</h4>
      <ul>
        <li v-for="server in servers" :key="server.identifier">
          <span class="sdot" :class="serverLevel(server.state).level"></span>
          <span class="sname">{{ server.name }}</span>
          <span class="muted mono small">{{ server.identifier }}</span>
          <span class="spacer"></span>
          <span class="small secondary">{{ serverLevel(server.state).label }}</span>
        </li>
      </ul>
    </div>

    <footer>
      <button class="btn small" :disabled="!!busy" data-action="status" @click="run('status')">
        <Icon :name="busy === 'status' ? 'loader' : 'activity'" :size="14" />連線測試
      </button>
      <button class="btn small" :disabled="!!busy" data-action="verify" @click="run('verify')">
        <Icon :name="busy === 'verify' ? 'loader' : 'shield'" :size="14" />簽章驗證
      </button>
      <button class="btn small" :disabled="!!busy" data-action="wol" @click="run('wol')">
        <Icon :name="busy === 'wol' ? 'loader' : 'power'" :size="14" />發送 WOL
      </button>
    </footer>
    <div v-if="last" class="last-result" :class="last.ok ? 'ok' : 'bad'">
      <Icon :name="last.ok ? 'check' : 'x'" :size="14" :stroke="3" />
      <span><strong>{{ LABELS[last.action] }}</strong>：{{ last.detail }}（{{ last.elapsed_ms }} ms）</span>
    </div>

    <div v-if="isSim && sim" class="sim">
      <span class="chip">模擬電源：{{ { on: '開機', off: '關機', booting: '開機中', shutting_down: '關機中' }[sim.power] }}</span>
      <label class="small">
        故障注入
        <select class="select" :value="sim.fault" :data-fault="agent.index" @change="setFault">
          <option v-for="(label, key) in s.simulation.agent_faults" :key="key" :value="key">{{ label }}</option>
        </select>
      </label>
      <button class="btn small ghost" @click="setPower(sim.power === 'off' ? 'on' : 'off')">
        {{ sim.power === 'off' ? '模擬開機' : '模擬斷電' }}
      </button>
    </div>
  </article>
</template>

<style scoped>
.agent {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
header {
  display: flex;
  align-items: center;
  gap: 10px;
}
.avatar {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  --c: var(--neutral);
  background: color-mix(in srgb, var(--c) 18%, var(--surface));
}
.avatar.good { --c: var(--good); }
.avatar.critical { --c: var(--critical); }
.titles {
  flex: 1;
  min-width: 0;
}
h3 {
  margin: 0;
  font-size: 15px;
}
.small {
  font-size: 12px;
}
.platform {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.warn-chip {
  color: var(--critical);
}
.resources {
  display: grid;
  gap: 8px;
}
.res-label {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--text-2);
  margin-bottom: 3px;
}
.caps {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.servers ul {
  list-style: none;
  margin: 0;
  padding: 0;
}
.servers li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}
.servers li:last-child {
  border-bottom: 0;
}
.sdot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
  background: var(--neutral);
}
.sdot.good { background: var(--good); }
.sdot.warning { background: var(--warning); }
.sdot.critical { background: var(--critical); }
.sname {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
footer {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.last-result {
  display: flex;
  gap: 6px;
  align-items: flex-start;
  font-size: 12px;
  padding: 6px 10px;
  border-radius: 8px;
}
.last-result.ok {
  background: color-mix(in srgb, var(--good) 12%, var(--surface));
}
.last-result.bad {
  background: color-mix(in srgb, var(--critical) 12%, var(--surface));
}
.sim {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding-top: 10px;
  border-top: 1px dashed var(--border-strong);
}
.sim label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-2);
}
</style>
