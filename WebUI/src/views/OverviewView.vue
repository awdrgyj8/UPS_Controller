<script setup>
import { computed } from 'vue'
import Icon from '../components/Icon.vue'
import StatTile from '../components/StatTile.vue'
import Meter from '../components/Meter.vue'
import TopologyGraph from '../components/TopologyGraph.vue'
import FlowStepper from '../components/FlowStepper.vue'
import LineChart from '../components/LineChart.vue'
import EventList from '../components/EventList.vue'
import StatusPill from '../components/StatusPill.vue'
import { agentLevel, batteryLevel, isServerRunning, powerLevel, store } from '../store.js'
import { duration, num } from '../format.js'

const s = computed(() => store.state)
const ups = computed(() => s.value.ups)
const vars = computed(() => ups.value.variables || {})
const threshold = computed(() => s.value.settings.shutdown_battery_threshold)
const power = computed(() => powerLevel(ups.value))
const agents = computed(() => s.value.agents)
const online = computed(() => agents.value.filter((a) => a.online).length)
const servers = computed(() => s.value.ptero.servers || [])
const running = computed(() => servers.value.filter(isServerRunning).length)
const expected = computed(() => s.value.controller.expected_power_state)
const nodesLevel = computed(() => {
  if (!agents.value.length) return 'neutral'
  if (expected.value && online.value < agents.value.length) return 'critical'
  if (!expected.value && online.value > 0) return 'warning'
  return 'good'
})
const loadLevel = computed(() => (ups.value.load >= 90 ? 'critical' : ups.value.load >= 75 ? 'warning' : 'accent'))
const onBatteryFor = computed(() => {
  const since = s.value.simulation?.outage_started_at
  return since ? duration(store.now - since, true) : ''
})

// 觸發條件即時檢查：與控制器的判斷邏輯相同
const conditions = computed(() => {
  const exp = expected.value !== false
  if (exp) {
    return [
      { label: '節點預期為開機', ok: true },
      { label: 'NUT 可讀取 UPS 狀態', ok: ups.value.ok === true },
      { label: 'UPS 改由電池供電（ups.status 含 OB）', ok: ups.value.ok === true && ups.value.power === false },
      { label: `電量 ≤ ${threshold.value}%（目前 ${ups.value.battery ?? '-'}%）`, ok: ups.value.battery != null && ups.value.battery <= threshold.value },
    ]
  }
  return [
    { label: '節點預期為關機', ok: true },
    { label: 'NUT 可讀取 UPS 狀態', ok: ups.value.ok === true },
    { label: '市電已恢復（ups.status 不含 OB）', ok: ups.value.ok === true && ups.value.power === true },
  ]
})
const triggered = computed(() => conditions.value.every((c) => c.ok))

const series = (key) => store.history.map((sample) => ({ t: sample.t, v: sample[key] }))
const batterySeries = computed(() => series('battery'))
const loadSeries = computed(() => series('load'))
function openTopology(id) {
  location.hash = `#/topology?node=${id}`
}

const events = computed(() => [...(s.value.events || [])].reverse().slice(0, 10))
</script>

<template>
  <div class="grid">
    <section class="tiles" aria-label="即時數據">
      <StatTile label="市電" icon="plug" :value="power.label" :level="power.level"
                :sub="ups.ok ? `ups.status = ${ups.status}${onBatteryFor ? ` · 已停電 ${onBatteryFor}` : ''}` : ups.error" />
      <StatTile label="電池電量" icon="battery" :value="ups.battery != null ? ups.battery + '%' : '-'"
                :level="batteryLevel(ups.battery, threshold)" :sub="`關機門檻 ${threshold}%`">
        <Meter :value="ups.battery" :level="batteryLevel(ups.battery, threshold) === 'good' ? 'accent' : batteryLevel(ups.battery, threshold)"
               :marker="threshold" :marker-label="`關機門檻 ${threshold}%`" />
      </StatTile>
      <StatTile label="預估續航" icon="clock" :value="duration(ups.runtime, true)" sub="依目前負載估算" />
      <StatTile label="UPS 負載" icon="activity" :value="ups.load != null ? ups.load + '%' : '-'"
                :sub="vars['ups.realpower'] ? `${vars['ups.realpower']} W / ${vars['ups.realpower.nominal'] || '-'} W` : ''">
        <Meter :value="ups.load" :level="loadLevel" />
      </StatTile>
      <StatTile label="輸入電壓" icon="zap" :value="num(ups.input_voltage, 1, 'V')"
                :sub="ups.input_frequency != null ? `${num(ups.input_frequency, 2)} Hz · 額定 ${vars['input.voltage.nominal'] || '-'} V` : ''" />
      <StatTile label="輸出電壓" icon="power" :value="num(ups.output_voltage, 1, 'V')"
                :sub="ups.temperature != null ? `UPS 溫度 ${num(ups.temperature, 1)} °C` : ''" />
      <StatTile label="節點在線" icon="server" :value="`${online} / ${agents.length}`" :level="nodesLevel"
                :sub="`預期：${expected === false ? '關機' : '開機'}`" />
      <StatTile label="遊戲伺服器" icon="game" :value="`${running} / ${servers.length}`"
                :sub="s.ptero.ok === false ? '面板無法連線' : '運行中 / 總數'" :level="s.ptero.ok === false ? 'critical' : ''" />
    </section>

    <section class="grid cols-3">
      <div class="card span-2">
        <div class="card-header">
          <h2 class="card-title">連線拓撲</h2>
          <span class="card-sub">點擊「連線拓撲」頁面可查看各節點詳細資訊</span>
          <span class="spacer"></span>
          <a class="btn small ghost" href="#/topology"><Icon name="external" :size="13" />完整拓撲</a>
        </div>
        <div class="card-body">
          <TopologyGraph :state="s" compact @select="openTopology" />
          <div class="legend">
            <span><i class="key power"></i>電力</span>
            <span><i class="key network"></i>網路連線</span>
            <span><i class="key broken"></i>中斷 / 無回應</span>
            <span><i class="key idle"></i>待命</span>
          </div>
          <div class="table-wrap node-table">
            <table class="table">
              <thead>
                <tr><th>節點</th><th>狀態</th><th>位址</th><th class="num">延遲</th><th class="num">伺服器</th><th class="num">系統開機</th></tr>
              </thead>
              <tbody>
                <tr v-for="agent in agents" :key="agent.index">
                  <td><a :href="`#/topology?node=agent-${agent.index}`">{{ agent.name }}</a></td>
                  <td><StatusPill v-bind="agentLevel(agent, expected)" /></td>
                  <td class="mono">{{ agent.ip }}:{{ agent.port }}</td>
                  <td class="num">{{ agent.latency_ms != null ? agent.latency_ms + ' ms' : '-' }}</td>
                  <td class="num">{{ servers.filter((x) => x.agent_index === agent.index && isServerRunning(x)).length }} / {{ (agent.servers || []).length }}</td>
                  <td class="num">{{ duration(agent.system?.uptime_seconds, true) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div class="grid side">
        <div class="card">
          <div class="card-header"><h2 class="card-title">自動關機觸發條件</h2></div>
          <div class="card-body">
            <ul class="conditions">
              <li v-for="c in conditions" :key="c.label" :class="c.ok ? 'ok' : 'no'">
                <span class="mark"><Icon :name="c.ok ? 'check' : 'minus'" :size="11" :stroke="3" /></span>{{ c.label }}
              </li>
            </ul>
            <div class="verdict" :class="{ armed: triggered }">
              <Icon :name="triggered ? 'alert' : 'shield'" :size="15" />
              <span v-if="expected !== false">{{ triggered ? '條件全部成立：控制器將執行關機程序' : '條件未成立：維持節點開機' }}</span>
              <span v-else>{{ triggered ? '條件成立：控制器將發送 Wake-on-LAN' : '等待市電恢復後喚醒節點' }}</span>
            </div>
          </div>
        </div>
        <div class="card">
          <div class="card-header"><h2 class="card-title">控制流程</h2></div>
          <div class="card-body">
            <FlowStepper :sequence="s.controller.sequence" />
          </div>
        </div>
      </div>
    </section>

    <section class="grid cols-3">
      <div class="card">
        <div class="card-header">
          <h2 class="card-title">電池電量</h2><span class="card-sub">最近 15 分鐘 · %</span>
        </div>
        <div class="card-body">
          <LineChart :samples="batterySeries" :now="store.now" :window-sec="900" :min="0" :max="100" unit="%"
                     label="battery" :threshold="{ value: threshold, label: `關機門檻 ${threshold}%` }" />
        </div>
      </div>
      <div class="card">
        <div class="card-header">
          <h2 class="card-title">UPS 負載</h2><span class="card-sub">最近 15 分鐘 · %</span>
        </div>
        <div class="card-body">
          <LineChart :samples="loadSeries" :now="store.now" :window-sec="900" :min="0" :max="100" unit="%"
                     label="load" color="var(--accent)" />
        </div>
      </div>
      <div class="card">
        <div class="card-header">
          <h2 class="card-title">最近事件</h2><span class="spacer"></span>
          <a class="btn small ghost" href="#/logs">全部</a>
        </div>
        <div class="card-body events">
          <EventList :events="events" dense />
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.side {
  align-content: start;
}
.legend {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-2);
  margin-top: 8px;
}
.legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.key {
  width: 20px;
  height: 0;
  border-top: 2px solid;
}
.key.power { border-color: var(--power); }
.key.network { border-color: var(--network); }
.key.broken { border-color: var(--critical); border-top-style: dashed; }
.key.idle { border-color: var(--axis); border-top-style: dotted; }
.node-table {
  margin-top: 14px;
}
.node-table td {
  white-space: nowrap;
}
.node-table a {
  color: var(--text);
  font-weight: 500;
}
.conditions {
  list-style: none;
  margin: 0 0 12px;
  padding: 0;
  display: grid;
  gap: 6px;
  font-size: 13px;
}
.conditions li {
  display: flex;
  align-items: center;
  gap: 8px;
}
.conditions li.no {
  color: var(--text-2);
}
.mark {
  display: inline-grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--surface-3);
  color: var(--muted);
  flex: none;
}
.ok .mark {
  background: var(--good);
  color: #fff;
}
.verdict {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  background: color-mix(in srgb, var(--good) 10%, var(--surface));
}
.verdict.armed {
  background: color-mix(in srgb, var(--serious) 16%, var(--surface));
}
.events {
  max-height: 260px;
  overflow-y: auto;
}
</style>
