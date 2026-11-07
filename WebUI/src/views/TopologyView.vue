<script setup>
import { computed, reactive, ref } from 'vue'
import Icon from '../components/Icon.vue'
import StatusPill from '../components/StatusPill.vue'
import TopologyGraph from '../components/TopologyGraph.vue'
import AgentCard from '../components/AgentCard.vue'
import { PHASE_LEVEL, isServerRunning, powerLevel, serverStatus, store, wattsText } from '../store.js'
import { ago, bytes, clock, duration, num } from '../format.js'

const s = computed(() => store.state)
const layers = reactive({ power: true, network: true, servers: true })
const selected = ref(new URLSearchParams(location.hash.split('?')[1] || '').get('node') || 'controller')

const vars = computed(() => s.value.ups.variables || {})
const agent = computed(() => {
  const match = selected.value.match(/^agent-(\d+)$/)
  return match ? s.value.agents.find((a) => a.index === Number(match[1])) : null
})
const server = computed(() => {
  const match = selected.value.match(/^server-(.+)$/)
  return match ? (s.value.ptero.servers || []).find((x) => x.identifier === match[1]) : null
})
const serverHost = computed(() => (server.value ? s.value.agents.find((a) => a.index === server.value.agent_index) : null))
const settings = computed(() => s.value.settings)
</script>

<template>
  <div class="layout">
    <div class="card main">
      <div class="card-header">
        <h2 class="card-title">系統連線拓撲</h2>
        <span class="spacer"></span>
        <label class="toggle"><input v-model="layers.power" type="checkbox" /><i class="key power"></i>電力線路</label>
        <label class="toggle"><input v-model="layers.network" type="checkbox" /><i class="key network"></i>網路連線</label>
        <label class="toggle"><input v-model="layers.servers" type="checkbox" />遊戲伺服器</label>
      </div>
      <div class="card-body">
        <TopologyGraph :state="s" :layers="layers" :selected="selected" @select="selected = $event" />
        <div class="legend">
          <span><i class="key power flow"></i>供電中（動畫表示電流方向）</span>
          <span><i class="key network"></i>連線正常</span>
          <span><i class="key broken"></i>中斷 / 無回應</span>
          <span><i class="key idle"></i>待命 / 未供電</span>
        </div>
      </div>
    </div>

    <aside class="card detail" data-testid="topology-detail">
      <div class="card-body">
        <!-- 市電 -->
        <template v-if="selected === 'grid'">
          <h3><Icon name="plug" />市電輸入</h3>
          <StatusPill v-bind="s.ups.ok ? (s.ups.power ? { level: 'good', label: '供電正常' } : { level: 'critical', label: '停電' }) : { level: 'neutral', label: '未知' }" />
          <dl class="kv">
            <dt>輸入電壓</dt><dd>{{ num(s.ups.input_voltage, 1, 'V') }}（額定 {{ vars['input.voltage.nominal'] || '-' }} V）</dd>
            <dt>輸入頻率</dt><dd>{{ num(s.ups.input_frequency, 2, 'Hz') }}</dd>
            <dt>切換電壓</dt><dd>低 {{ vars['input.transfer.low'] || '-' }} V / 高 {{ vars['input.transfer.high'] || '-' }} V</dd>
            <template v-if="s.simulation?.outage_started_at">
              <dt>停電時間</dt><dd>{{ duration(store.now - s.simulation.outage_started_at) }}</dd>
            </template>
          </dl>
          <p class="hint">輸入電壓超出切換範圍時，UPS 會改由電池供電（ups.status 出現 OB）。</p>
        </template>

        <!-- UPS -->
        <template v-else-if="selected === 'ups'">
          <h3><Icon name="battery" />{{ vars['ups.model'] || vars['device.model'] || 'UPS' }}</h3>
          <StatusPill v-bind="powerLevel(s.ups)" />
          <div class="flags">
            <span v-for="flag in s.ups.status_flags" :key="flag.code" class="chip"><b class="mono">{{ flag.code }}</b>{{ flag.label }}</span>
          </div>
          <dl class="kv">
            <dt>製造商</dt><dd>{{ vars['ups.mfr'] || vars['device.mfr'] || '-' }}</dd>
            <dt>序號</dt><dd class="mono">{{ vars['ups.serial'] || vars['device.serial'] || '-' }}</dd>
            <dt>電量</dt><dd>{{ s.ups.battery ?? '-' }}%（門檻 {{ settings.shutdown_battery_threshold }}%）</dd>
            <dt>預估續航</dt><dd>{{ duration(s.ups.runtime) }}</dd>
            <dt>負載</dt><dd>{{ s.ups.load ?? '-' }}%（{{ wattsText(s.ups) }}{{ s.ups.realpower_estimated ? '，估算' : '' }}）</dd>
            <dt>電池電壓</dt><dd>{{ num(s.ups.battery_voltage, 1, 'V') }}</dd>
            <dt>輸出電壓</dt><dd>{{ num(s.ups.output_voltage, 1, 'V') }}</dd>
            <dt>溫度</dt><dd>{{ num(s.ups.temperature, 1, '°C') }}</dd>
          </dl>
          <a class="btn small" href="#/ups"><Icon name="external" :size="13" />查看全部 UPS 數據</a>
        </template>

        <!-- NUT -->
        <template v-else-if="selected === 'nut'">
          <h3><Icon name="database" />NUT Server</h3>
          <StatusPill v-bind="s.nut.connected ? { level: 'good', label: '已連線' } : { level: 'critical', label: '斷線' }" />
          <dl class="kv">
            <dt>位址</dt><dd class="mono">{{ s.nut.host }}:{{ s.nut.port }}</dd>
            <dt>UPS 名稱</dt><dd class="mono">{{ s.nut.ups_name }}</dd>
            <dt>驗證</dt><dd>{{ s.nut.auth ? '使用帳號密碼' : '未使用' }}</dd>
            <dt>回應時間</dt><dd>{{ s.nut.latency_ms != null ? s.nut.latency_ms + ' ms' : '-' }}</dd>
            <dt>最後更新</dt><dd>{{ ago(s.nut.last_update, store.now) }}</dd>
            <dt>Driver</dt><dd>{{ vars['driver.name'] || '-' }} {{ vars['driver.version'] || '' }}</dd>
            <dt>變數數量</dt><dd>{{ Object.keys(vars).length }}</dd>
          </dl>
          <div v-if="s.nut.error" class="notice critical">{{ s.nut.error }}</div>
        </template>

        <!-- Controller -->
        <template v-else-if="selected === 'controller'">
          <h3><Icon name="cpu" />Controller</h3>
          <StatusPill :level="PHASE_LEVEL[s.controller.phase]" :label="s.controller.phase_label" />
          <p class="decision">{{ s.controller.decision }}</p>
          <dl class="kv">
            <dt>主機名稱</dt><dd>{{ s.controller.hostname }}</dd>
            <dt>模式</dt><dd>{{ s.mode === 'simulation' ? '模擬' : '實機' }}</dd>
            <dt>節點預期</dt><dd>{{ s.controller.expected_power_state === false ? '關機' : '開機' }}</dd>
            <dt>自動控制</dt><dd>{{ s.controller.paused ? '已暫停' : '啟用' }}</dd>
            <dt>輪詢次數</dt><dd>{{ s.controller.cycle_count }}（上次 {{ clock(s.controller.last_cycle_at) }}）</dd>
            <dt>輪詢間隔</dt><dd>{{ settings.poll_interval }} 秒（UPS 監控 {{ settings.monitor_interval }} 秒）</dd>
            <dt>關機門檻</dt><dd>電量 ≤ {{ settings.shutdown_battery_threshold }}%</dd>
            <dt>伺服器等待</dt><dd>{{ settings.server_stop_max_attempts }} 次 × {{ settings.server_stop_check_interval }} 秒</dd>
            <dt>WOL</dt><dd>{{ settings.wol_attempts }} 輪 × {{ settings.wol_interval }} 秒</dd>
            <dt>電源狀態檔</dt><dd class="mono small">{{ settings.power_state_path }}</dd>
            <dt>Web 驗證</dt><dd>{{ settings.auth_required ? '已啟用 WEB_TOKEN' : '未啟用' }}</dd>
          </dl>
        </template>

        <!-- 面板 -->
        <template v-else-if="selected === 'panel'">
          <h3><Icon name="panel" />Pterodactyl 面板</h3>
          <StatusPill v-bind="s.ptero.ok ? { level: 'good', label: '連線正常' } : s.ptero.configured === false ? { level: 'neutral', label: '未設定' } : { level: 'critical', label: '無法連線' }" />
          <dl class="kv">
            <dt>URL</dt><dd class="mono small">{{ s.ptero.url || '-' }}</dd>
            <dt>Node</dt><dd>{{ s.ptero.nodes.length }} 個</dd>
            <dt>伺服器</dt><dd>{{ s.ptero.servers.length }} 台（運行 {{ s.ptero.servers.filter(isServerRunning).length }}）</dd>
            <dt>最後更新</dt><dd>{{ ago(s.ptero.updated_at, store.now) }}</dd>
          </dl>
          <div v-if="s.ptero.error" class="notice critical">{{ s.ptero.error }}</div>
          <h4 class="section-title">Nodes</h4>
          <ul class="plain">
            <li v-for="node in s.ptero.nodes" :key="node.id"><span class="mono">#{{ node.id }}</span> {{ node.name }} <span class="muted mono">{{ node.fqdn }}</span></li>
          </ul>
        </template>

        <!-- Agent -->
        <AgentCard v-else-if="agent" :agent="agent" flat />

        <!-- 遊戲伺服器 -->
        <template v-else-if="server">
          <h3><Icon name="game" />{{ server.name }}</h3>
          <StatusPill v-bind="serverStatus(server)" />
          <p v-if="serverStatus(server).assumed" class="hint">
            面板回報為 starting（啟動中），但已運行超過 1 小時，視為運行中。通常是面板偵測不到啟動完成的訊息，
            可在面板的 Startup 設定調整「啟動完成」的判斷字串。
          </p>
          <dl class="kv">
            <dt>Identifier</dt><dd class="mono">{{ server.identifier }}</dd>
            <dt>UUID</dt><dd class="mono small">{{ server.uuid }}</dd>
            <dt>所屬節點</dt><dd>{{ serverHost?.name || '-' }}（node #{{ server.node_id }} {{ server.node_name }}）</dd>
            <dt>CPU</dt><dd>{{ num(server.cpu_percent, 1, '%') }}</dd>
            <dt>記憶體</dt><dd>{{ bytes(server.memory_bytes) }}</dd>
            <dt>運行時間</dt><dd>{{ server.uptime_ms ? duration(server.uptime_ms / 1000, true) : '-' }}</dd>
          </dl>
          <div v-if="server.error" class="notice critical">{{ server.error }}</div>
          <p class="hint">停電關機程序的第一步會對面板上所有伺服器送出 stop，全部變成 offline 後才會關閉節點。</p>
        </template>

        <div v-else class="empty">點選拓撲圖中的任一節點以查看詳細資訊</div>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 16px;
  align-items: start;
}
@media (max-width: 1200px) {
  .layout {
    grid-template-columns: minmax(0, 1fr);
  }
}
.detail {
  position: sticky;
  top: 16px;
}
.detail .card-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
h3 {
  margin: 0;
  font-size: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.detail :deep(.pill) {
  align-self: flex-start;
}
.flags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.flags b {
  margin-right: 2px;
}
.decision {
  margin: 0;
  font-weight: 500;
}
.hint {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
}
.small {
  font-size: 11.5px;
}
.plain {
  list-style: none;
  margin: 0;
  padding: 0;
  font-size: 13px;
  display: grid;
  gap: 4px;
}
.toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-2);
  cursor: pointer;
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
  display: inline-block;
  width: 20px;
  height: 0;
  border-top: 2px solid;
}
.key.power { border-color: var(--power); }
.key.network { border-color: var(--network); }
.key.broken { border-color: var(--critical); border-top-style: dashed; }
.key.idle { border-color: var(--axis); border-top-style: dotted; }
</style>
