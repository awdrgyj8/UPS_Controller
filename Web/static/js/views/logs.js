import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api.js'
import { SOURCES } from '../store.js'

const LEVELS = [
  { id: 'error', label: '錯誤' },
  { id: 'warning', label: '警告' },
  { id: 'success', label: '成功' },
  { id: 'info', label: '資訊' },
]

// 事件紀錄頁：依等級、來源、關鍵字篩選，並可匯出 JSON
export default {
  name: 'LogsView',
  setup() {
    const events = ref([])
    const level = ref('')
    const source = ref('')
    const query = ref('')
    let timer = null

    async function load() {
      try {
        events.value = (await api('/api/events?limit=1000')).events
      } catch {
        /* 保留上一次的資料 */
      }
    }
    onMounted(() => {
      load()
      timer = setInterval(load, 3000)
    })
    onBeforeUnmount(() => clearInterval(timer))

    const sources = computed(() => [...new Set(events.value.map((e) => e.source))].sort())
    const counts = computed(() => {
      const c = {}
      for (const e of events.value) c[e.level] = (c[e.level] || 0) + 1
      return c
    })
    const filtering = computed(() => Boolean(level.value || source.value || query.value.trim()))
    const filtered = computed(() => {
      const q = query.value.trim().toLowerCase()
      return events.value
        .filter((e) => (!level.value || e.level === level.value) && (!source.value || e.source === source.value))
        .filter((e) => !q || e.message.toLowerCase().includes(q))
        .slice()
        .reverse()
    })
    // 再按一次同一個等級就取消篩選
    const pick = (id) => (level.value = level.value === id ? '' : id)

    function download() {
      const blob = new Blob([JSON.stringify(events.value, null, 2)], { type: 'application/json' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `ups-controller-events-${Date.now()}.json`
      a.click()
      URL.revokeObjectURL(a.href)
    }

    return { LEVELS, SOURCES, events, level, source, query, sources, counts, filtering, filtered, pick, download }
  },
  template: /* html */ `
    <div class="v-logs">
      <div class="grid">
        <div class="levels" role="group" aria-label="等級">
          <button class="tile deep all" :aria-pressed="level === ''" data-level="" @click="level = ''">
            <span class="label">全部</span><span class="big">{{ events.length }}</span>
          </button>
          <button v-for="l in LEVELS" :key="l.id" class="tile" :class="l.id" :aria-pressed="level === l.id"
                  :data-level="l.id" @click="pick(l.id)">
            <span class="label">{{ l.label }}</span><span class="big">{{ counts[l.id] || 0 }}</span>
          </button>
        </div>

        <section class="tile list" aria-label="事件">
          <div class="tools">
            <input v-model="query" class="input" type="search" placeholder="搜尋" aria-label="搜尋事件" data-testid="log-search" />
            <select v-model="source" class="select" aria-label="來源" data-testid="log-source">
              <option value="">所有來源</option>
              <option v-for="src in sources" :key="src" :value="src">{{ SOURCES[src] || src }}</option>
            </select>
            <button class="btn" data-testid="log-export" :disabled="!events.length" @click="download">匯出 JSON</button>
          </div>
          <div data-testid="log-list">
            <EventList v-if="filtered.length" :events="filtered" />
            <div v-else class="empty">{{ filtering ? '沒有符合的事件' : '還沒有事件' }}</div>
          </div>
        </section>
      </div>
    </div>`,
}
