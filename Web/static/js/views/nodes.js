import { computed, ref } from 'vue'
import AgentCard from '../components/agent-card.js'
import { act, isServerRunning, serverStatus, store } from '../store.js'
import { bytes, duration, num } from '../format.js'

// 節點與伺服器：左上是在線數，旁邊每台節點一塊磚，下面是面板上所有伺服器
export default {
  name: 'NodesView',
  components: { AgentCard },
  setup() {
    const s = computed(() => store.state)
    const agents = computed(() => s.value.agents || [])
    const online = computed(() => agents.value.filter((a) => a.online).length)
    const servers = computed(() => s.value.ptero.servers || [])
    const running = computed(() => servers.value.filter(isServerRunning).length)
    const isSim = computed(() => s.value.mode === 'simulation')
    const stuck = computed(() => {
      const map = {}
      for (const server of s.value.simulation?.servers || []) map[server.identifier] = server.stuck
      return map
    })

    // 一排最多幾塊節點磚：4 台排成 2×2，其餘最多 3 欄；最後一排不滿時會自動撐滿
    const perRow = computed(() => {
      const n = agents.value.length
      return n <= 3 ? Math.max(n, 1) : n === 4 ? 2 : 3
    })
    // 數字越長字級越小，才不會擠出磚外
    const size = (a, b) => {
      const len = `${a}/${b}`.length
      return len <= 3 ? 'c3' : len === 4 ? 'c4' : 'c5'
    }

    // 伺服器依所屬節點排在一起，節點名稱只在每組第一列出現
    const rows = computed(() => {
      const order = new Map(agents.value.map((agent, i) => [agent.index, i]))
      const rank = (server) => (order.has(server.agent_index) ? order.get(server.agent_index) : Infinity)
      const sorted = [...servers.value].sort((a, b) => rank(a) - rank(b))
      return sorted.map((server, i) => {
        const agent = agents.value.find((a) => a.index === server.agent_index)
        return {
          server,
          status: serverStatus(server),
          first: i === 0 || rank(sorted[i - 1]) !== rank(server),
          node: agent?.name || '',
          panelNode: `#${server.node_id}${server.node_name ? ' ' + server.node_name : ''}`,
        }
      })
    })

    const panel = computed(() => {
      const ptero = s.value.ptero
      if (ptero.ok) return { level: 'good', label: '面板已連線' }
      if (ptero.configured === false) return { level: 'neutral', label: '面板未設定' }
      if (ptero.ok === false) return { level: 'critical', label: '面板連不上' }
      return { level: 'neutral', label: '讀取中' }
    })

    const refreshing = ref(false)
    async function refresh() {
      refreshing.value = true
      await act('/api/control/refresh', undefined, '已重新整理')
      refreshing.value = false
    }
    async function toggleStuck(server) {
      const value = !stuck.value[server.identifier]
      await act(`/api/sim/servers/${server.identifier}/stuck`, { value }, value ? '已設為關不掉' : '已恢復正常')
    }

    return { s, agents, online, servers, running, isSim, stuck, perRow, size, rows, panel, refreshing, refresh, toggleStuck, isServerRunning, bytes, duration, num }
  },
  template: /* html */ `
    <div class="v-nodes">
      <div v-if="s.agent_config_error" class="notice critical">{{ s.agent_config_error }}</div>

      <div class="grid">
        <div class="side span-3">
          <section class="tile lime count" aria-label="節點在線">
            <div class="tile-head">
              <div class="label">節點在線</div>
              <button class="icon-btn" aria-label="重新整理" title="重新整理" :disabled="refreshing" @click="refresh">
                <Icon :name="refreshing ? 'loader' : 'refresh'" :size="17" />
              </button>
            </div>
            <div class="big" :class="size(online, agents.length)" data-testid="agents-online">{{ online }}<em>/{{ agents.length }}</em></div>
          </section>
          <section class="tile tint count" aria-label="伺服器運行">
            <div class="label">伺服器運行</div>
            <div class="big" :class="size(running, servers.length)" data-testid="servers-running">{{ running }}<em>/{{ servers.length }}</em></div>
            <div v-if="servers.length" class="pips" aria-hidden="true">
              <i v-for="server in servers" :key="server.identifier" :class="{ stopped: !isServerRunning(server) }"></i>
            </div>
          </section>
        </div>

        <div class="agents span-9" :style="{ '--per-row': perRow }">
          <AgentCard v-for="agent in agents" :key="agent.index" :agent="agent" />
          <div v-if="!agents.length" class="tile no-agents">
            <div class="title">還沒有節點</div>
            <p class="aside">在 .env 的 AgentInfo 加入裝了 UPS_Agent 的主機</p>
          </div>
        </div>

        <section class="tile deep servers span-12" data-testid="server-list" aria-label="伺服器">
          <div class="tile-head">
            <div class="label">伺服器</div>
            <StatusPill :level="panel.level" :label="panel.label" />
          </div>
          <div v-if="s.ptero.error" class="notice critical">{{ s.ptero.error }}</div>
          <div class="table-wrap">
            <table class="table">
              <thead>
                <tr>
                  <th>節點</th><th>名稱</th><th>狀態</th>
                  <th class="num">CPU</th><th class="num">記憶體</th><th class="num">已運行</th>
                  <th v-if="isSim" class="num">模擬</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in rows" :key="row.server.identifier" :class="{ first: row.first }" :data-server="row.server.identifier">
                  <td class="node-cell">
                    <template v-if="row.first">
                      <template v-if="row.node">{{ row.node }}</template>
                      <span v-else class="pill warning">未對應</span>
                    </template>
                    <span v-if="!row.node" class="aside panel-node">{{ row.panelNode }}</span>
                  </td>
                  <td class="name-cell" :title="row.server.identifier">{{ row.server.name }}</td>
                  <td>
                    <StatusPill :level="row.status.level" :label="row.status.label" />
                    <span v-if="row.status.assumed" class="aside assumed">面板回報啟動中</span>
                  </td>
                  <td class="num">{{ row.server.cpu_percent != null ? num(row.server.cpu_percent, 1) + '%' : '-' }}</td>
                  <td class="num">{{ bytes(row.server.memory_bytes) }}</td>
                  <td class="num">{{ row.server.uptime_ms ? duration(row.server.uptime_ms / 1000, true) : '-' }}</td>
                  <td v-if="isSim" class="num">
                    <button class="btn small" :class="{ danger: stuck[row.server.identifier] }" data-action="stuck"
                            :aria-pressed="!!stuck[row.server.identifier]" @click="toggleStuck(row.server)">
                      {{ stuck[row.server.identifier] ? '解除卡住' : '讓它關不掉' }}
                    </button>
                  </td>
                </tr>
                <tr v-if="!rows.length">
                  <td :colspan="isSim ? 7 : 6" class="empty">{{ s.ptero.configured === false ? '沒有設定面板' : '面板上沒有伺服器' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>`,
}
