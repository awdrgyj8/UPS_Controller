<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import EventList from '../components/EventList.vue'
import Icon from '../components/Icon.vue'
import { api } from '../api.js'
import { store } from '../store.js'

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

const LEVELS = [
  { id: '', label: '全部' },
  { id: 'error', label: '錯誤' },
  { id: 'warning', label: '警告' },
  { id: 'success', label: '成功' },
  { id: 'info', label: '資訊' },
]
const sources = computed(() => [...new Set(events.value.map((e) => e.source))].sort())
const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  return events.value
    .filter((e) => (!level.value || e.level === level.value) && (!source.value || e.source === source.value))
    .filter((e) => !q || e.message.toLowerCase().includes(q))
    .slice()
    .reverse()
})
const counts = computed(() => {
  const c = {}
  for (const e of events.value) c[e.level] = (c[e.level] || 0) + 1
  return c
})

function download() {
  const blob = new Blob([JSON.stringify(events.value, null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `ups-controller-events-${Date.now()}.json`
  a.click()
  URL.revokeObjectURL(a.href)
}
</script>

<template>
  <section class="card">
    <div class="card-header">
      <h2 class="card-title">事件紀錄</h2>
      <span class="card-sub">保留最近 1000 筆（重新啟動後清空）</span>
      <span class="spacer"></span>
      <button class="btn small" @click="download"><Icon name="external" :size="13" />匯出 JSON</button>
    </div>
    <div class="card-body filters">
      <div class="segmented">
        <button v-for="l in LEVELS" :key="l.id" :class="{ active: level === l.id }" @click="level = l.id">
          {{ l.label }}<span v-if="l.id && counts[l.id]" class="count">{{ counts[l.id] }}</span>
        </button>
      </div>
      <select v-model="source" class="select">
        <option value="">所有來源</option>
        <option v-for="src in sources" :key="src" :value="src">{{ src }}</option>
      </select>
      <input v-model="query" class="input search" type="search" placeholder="搜尋訊息…" />
    </div>
    <div class="card-body">
      <EventList :events="filtered" />
    </div>
  </section>
</template>

<style scoped>
.filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  padding-bottom: 0;
}
.search {
  flex: 1;
  min-width: 180px;
}
.count {
  margin-left: 4px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}
</style>
