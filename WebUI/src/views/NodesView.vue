<script setup>
import { computed } from 'vue'
import AgentCard from '../components/AgentCard.vue'
import StatusPill from '../components/StatusPill.vue'
import Icon from '../components/Icon.vue'
import { act, serverStatus, store } from '../store.js'
import { ago, bytes, duration, num } from '../format.js'

const s = computed(() => store.state)
const servers = computed(() => s.value.ptero.servers || [])
const agentName = (index) => s.value.agents.find((a) => a.index === index)?.name || '—'
const isSim = computed(() => s.value.mode === 'simulation')
const simServers = computed(() => {
  const map = {}
  for (const server of s.value.simulation?.servers || []) map[server.identifier] = server
  return map
})

async function refresh() {
  await act('/api/control/refresh', undefined, '已重新整理節點與伺服器狀態')
}

async function toggleStuck(server) {
  const stuck = !simServers.value[server.identifier]?.stuck
  await act(`/api/sim/servers/${server.identifier}/stuck`, { value: stuck }, stuck ? '已設定為無法關閉' : '已恢復正常')
}
</script>

<template>
  <div class="grid">
    <div class="toolbar">
      <h2>節點（Agent）</h2>
      <span class="muted">{{ s.agents.filter((a) => a.online).length }} / {{ s.agents.length }} 在線 · 更新於 {{ ago(s.agents_updated_at, store.now) }}</span>
      <span class="spacer"></span>
      <button class="btn" @click="refresh"><Icon name="refresh" :size="14" />立即重新整理</button>
    </div>
    <div v-if="s.agent_config_error" class="notice critical">{{ s.agent_config_error }}</div>
    <section class="agents">
      <AgentCard v-for="agent in s.agents" :key="agent.index" :agent="agent" />
    </section>

    <section class="card">
      <div class="card-header">
        <h2 class="card-title">Pterodactyl 遊戲伺服器</h2>
        <span class="card-sub">{{ servers.length }} 台 · 更新於 {{ ago(s.ptero.updated_at, store.now) }}</span>
        <span class="spacer"></span>
        <StatusPill v-bind="s.ptero.ok ? { level: 'good', label: '面板連線正常' } : s.ptero.configured === false ? { level: 'neutral', label: '面板未設定' } : { level: 'critical', label: '面板無法連線' }" />
      </div>
      <div v-if="s.ptero.error" class="card-body"><div class="notice critical">{{ s.ptero.error }}</div></div>
      <div class="card-body table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>名稱</th><th>Identifier</th><th>所屬節點</th><th>Node</th><th>狀態</th>
              <th class="num">CPU</th><th class="num">記憶體</th><th class="num">運行時間</th>
              <th v-if="isSim">模擬故障</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="server in servers" :key="server.identifier">
              <td>{{ server.name }}</td>
              <td class="mono">{{ server.identifier }}</td>
              <td>{{ agentName(server.agent_index) }}</td>
              <td>#{{ server.node_id }} {{ server.node_name }}</td>
              <td>
                <StatusPill v-bind="serverStatus(server)" />
                <div v-if="serverStatus(server).assumed" class="muted assumed">面板回報 starting</div>
              </td>
              <td class="num">{{ num(server.cpu_percent, 1, '%') }}</td>
              <td class="num">{{ bytes(server.memory_bytes) }}</td>
              <td class="num">{{ server.uptime_ms ? duration(server.uptime_ms / 1000, true) : '-' }}</td>
              <td v-if="isSim">
                <button class="btn small" :class="{ danger: simServers[server.identifier]?.stuck }" @click="toggleStuck(server)">
                  {{ simServers[server.identifier]?.stuck ? '解除卡住' : '設為無法關閉' }}
                </button>
              </td>
            </tr>
            <tr v-if="!servers.length"><td :colspan="isSim ? 9 : 8" class="empty">沒有伺服器資料</td></tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.assumed {
  font-size: 11px;
  margin-top: 2px;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
h2 {
  margin: 0;
  font-size: 17px;
}
.agents {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
}
@media (max-width: 420px) {
  .agents {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
