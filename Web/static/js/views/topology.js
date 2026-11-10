import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import TopologyGraph from '../components/topology-graph.js'
import { PHASE_LEVEL, agentLevel, isServerRunning, powerLevel, serverStatus, store } from '../store.js'
import { ago, bytes, duration, num } from '../format.js'

const LAYERS = [
  { id: 'power', label: '電力' },
  { id: 'network', label: '資料' },
  { id: 'servers', label: '伺服器' },
]
const nodeFromHash = () => new URLSearchParams(location.hash.split('?')[1] || '').get('node')

export default {
  name: 'TopologyView',
  components: { TopologyGraph },
  setup() {
    const s = computed(() => store.state)
    const layers = reactive({ power: true, network: true, servers: true })
    const selected = ref(nodeFromHash() || 'controller')
    const onHash = () => {
      const node = nodeFromHash()
      if (node) selected.value = node
    }
    window.addEventListener('hashchange', onHash)
    onBeforeUnmount(() => window.removeEventListener('hashchange', onHash))

    const ups = computed(() => s.value.ups)
    const vars = computed(() => ups.value.variables || {})
    const settings = computed(() => s.value.settings)
    const servers = computed(() => s.value.ptero.servers || [])
    const agent = computed(() => {
      const match = selected.value.match(/^agent-(\d+)$/)
      return match ? s.value.agents.find((a) => a.index === Number(match[1])) : null
    })
    const server = computed(() => {
      const match = selected.value.match(/^server-(.+)$/)
      return match ? servers.value.find((x) => x.identifier === match[1]) : null
    })

    // 右側面板的內容：標題、狀態、鍵值列表，依選到的節點產生
    const detail = computed(() => {
      const st = s.value
      const u = ups.value
      const v = vars.value
      const rows = (list) => list.filter((row) => row && row[1] !== '' && row[1] != null && row[1] !== '-')
      switch (selected.value) {
        case 'grid':
          return {
            title: '市電',
            status: u.ok ? (u.power ? { level: 'good', label: '供電中' } : { level: 'critical', label: '停電' }) : { level: 'neutral', label: '未知' },
            rows: rows([
              ['電壓', num(u.input_voltage, 1, 'V')],
              ['頻率', num(u.input_frequency, 2, 'Hz')],
              v['input.transfer.low'] && ['切換範圍', `${v['input.transfer.low']}–${v['input.transfer.high'] || '?'} V`],
              u.ok && u.power === false && u.on_battery_since && ['已停電', duration(store.now - u.on_battery_since)],
            ]),
          }
        case 'ups':
          return {
            title: v['ups.model'] || v['device.model'] || 'UPS',
            status: powerLevel(u),
            flags: u.status_flags || [],
            rows: rows([
              ['電量', u.battery != null ? `${u.battery}%` : ''],
              ['續航', duration(u.runtime)],
              ['負載', u.load != null ? `${u.load}%` : ''],
              ['輸出', num(u.output_voltage, 1, 'V')],
              ['電池電壓', num(u.battery_voltage, 1, 'V')],
              ['序號', v['ups.serial'] || v['device.serial']],
            ]),
            link: { href: '#/ups', label: 'UPS 數據' },
            error: u.ok === false ? u.error : '',
          }
        case 'nut':
          return {
            title: 'NUT Server',
            status: st.nut.connected ? { level: 'good', label: '已連線' } : st.nut.connected === false ? { level: 'critical', label: '斷線' } : { level: 'neutral', label: '連線中' },
            rows: rows([
              ['位址', `${st.nut.host}:${st.nut.port}`],
              ['UPS 名稱', st.nut.ups_name],
              ['回應', st.nut.latency_ms != null ? `${st.nut.latency_ms} ms` : ''],
              ['更新', ago(st.nut.last_update, store.now)],
              ['Driver', [v['driver.name'], v['driver.version']].filter(Boolean).join(' ')],
            ]),
            error: st.nut.error,
          }
        case 'controller':
          return {
            title: 'Controller',
            status: { level: PHASE_LEVEL[st.controller.phase] || 'neutral', label: st.controller.phase_label },
            rows: rows([
              ['主機', st.controller.hostname],
              ['節點應', st.controller.expected_power_state === false ? '關機' : '開機'],
              ['自動控制', st.controller.paused ? '已暫停' : '啟用'],
              ['檢查間隔', `${settings.value.poll_interval} 秒`],
              ['關機門檻', `${settings.value.shutdown_battery_threshold}%`],
              ['等伺服器停止', `${settings.value.server_stop_max_attempts} 次 × ${settings.value.server_stop_check_interval} 秒`],
              ['WOL', `${settings.value.wol_attempts} 輪 × ${settings.value.wol_interval} 秒`],
              ['存取權杖', settings.value.auth_required ? '已啟用' : '未啟用'],
            ]),
          }
        case 'panel':
          return {
            title: 'Pterodactyl',
            status: st.ptero.ok ? { level: 'good', label: '已連線' } : st.ptero.configured === false ? { level: 'neutral', label: '未設定' } : { level: 'critical', label: '無法連線' },
            rows: rows([
              ['網址', st.ptero.url],
              ['伺服器', `${servers.value.filter(isServerRunning).length}/${servers.value.length} 運行`],
              ['更新', ago(st.ptero.updated_at, store.now)],
              ...(st.ptero.nodes || []).map((node) => [`Node #${node.id}`, node.name]),
            ]),
            error: st.ptero.error,
          }
      }
      if (agent.value) {
        const a = agent.value
        const hosted = servers.value.filter((x) => x.agent_index === a.index)
        return {
          title: a.name,
          status: agentLevel(a, st.controller.expected_power_state),
          rows: rows([
            ['位址', `${a.ip}:${a.port}`],
            ['MAC', a.mac],
            ['延遲', a.latency_ms != null ? `${a.latency_ms} ms` : ''],
            ['已開機', duration(a.system?.uptime_seconds, true)],
            ['伺服器', hosted.length ? `${hosted.filter(isServerRunning).length}/${hosted.length} 運行` : ''],
            ['上次回應', a.online ? '' : ago(a.last_seen, store.now)],
          ]),
          link: { href: '#/nodes', label: '節點與伺服器' },
          error: a.online ? '' : a.error,
        }
      }
      if (server.value) {
        const x = server.value
        const status = serverStatus(x)
        const host = st.agents.find((a) => a.index === x.agent_index)
        return {
          title: x.name,
          status,
          note: status.assumed ? '面板回報啟動中，但已運行超過 1 小時，視為運行中。' : '',
          rows: rows([
            ['節點', host?.name || x.node_name],
            ['CPU', num(x.cpu_percent, 1, '%')],
            ['記憶體', bytes(x.memory_bytes)],
            ['已運行', x.uptime_ms ? duration(x.uptime_ms / 1000, true) : ''],
            ['ID', x.identifier],
          ]),
          error: x.error,
        }
      }
      return null
    })

    return { s, LAYERS, layers, selected, detail }
  },
  template: /* html */ `
    <main class="v-topology grid">
      <section class="tile deep graph" aria-label="連線拓撲">
        <div class="tile-head">
          <h2 class="label">連線拓撲</h2>
          <div class="layers" role="group" aria-label="顯示圖層">
            <button v-for="layer in LAYERS" :key="layer.id" :aria-pressed="layers[layer.id]" :data-layer="layer.id"
                    @click="layers[layer.id] = !layers[layer.id]">{{ layer.label }}</button>
          </div>
        </div>
        <TopologyGraph :state="s" :layers="layers" :selected="selected" @select="selected = $event" />
      </section>

      <aside class="tile detail" data-testid="topology-detail">
        <template v-if="detail">
          <div class="tile-head">
            <h2 class="title clip">{{ detail.title }}</h2>
            <StatusPill :level="detail.status.level" :label="detail.status.label" />
          </div>
          <div v-if="detail.flags && detail.flags.length" class="flags">
            <span v-for="flag in detail.flags" :key="flag.code" class="pill" :class="flag.level">{{ flag.code }} {{ flag.label }}</span>
          </div>
          <p v-if="detail.note" class="aside">{{ detail.note }}</p>
          <div v-if="detail.error" class="notice critical">{{ detail.error }}</div>
          <dl class="kv">
            <template v-for="row in detail.rows" :key="row[0]"><dt>{{ row[0] }}</dt><dd>{{ row[1] }}</dd></template>
          </dl>
          <a v-if="detail.link" class="btn small" :href="detail.link.href">{{ detail.link.label }}</a>
        </template>
        <div v-else class="empty">點選圖上的方塊</div>
      </aside>
    </main>`,
}
