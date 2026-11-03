<script setup>
import { computed } from 'vue'
import Icon from './Icon.vue'
import { TEST_STATUS } from '../store.js'

const props = defineProps({
  results: { type: Array, default: () => [] },
})

const groups = computed(() => {
  const map = new Map()
  for (const result of props.results) {
    if (!map.has(result.group)) map.set(result.group, [])
    map.get(result.group).push(result)
  }
  return [...map.entries()]
})
</script>

<template>
  <div class="results">
    <section v-for="[group, items] in groups" :key="group" class="group">
      <h4 class="section-title">{{ group }}</h4>
      <ul>
        <li v-for="item in items" :key="item.id" :class="TEST_STATUS[item.status]?.level" :data-test-id="item.id">
          <span class="badge" :title="TEST_STATUS[item.status]?.label">
            <Icon :name="TEST_STATUS[item.status]?.icon || 'circle'" :size="12" :stroke="3" />
          </span>
          <div class="body">
            <div class="label">
              {{ item.label }}
              <span v-if="item.dry_run" class="chip dry">乾跑</span>
              <span class="status-text">{{ TEST_STATUS[item.status]?.label }}</span>
            </div>
            <div v-if="item.detail" class="detail">{{ item.detail }}</div>
          </div>
          <span class="time tabular muted">{{ item.duration_ms != null ? item.duration_ms + ' ms' : '' }}</span>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.group + .group {
  margin-top: 16px;
}
ul {
  list-style: none;
  margin: 0;
  padding: 0;
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
}
li {
  display: grid;
  grid-template-columns: 22px 1fr auto;
  gap: 10px;
  padding: 9px 12px;
  align-items: start;
  --c: var(--neutral);
}
li + li {
  border-top: 1px solid var(--border);
}
li.good { --c: var(--good); }
li.warning { --c: var(--warning); background: color-mix(in srgb, var(--warning) 6%, transparent); }
li.critical { --c: var(--critical); background: color-mix(in srgb, var(--critical) 6%, transparent); }
li.info { --c: var(--info); }
.badge {
  display: inline-grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--c);
  color: #fff;
}
li.warning .badge { color: #0b0b0b; }
.label {
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.status-text {
  font-size: 12px;
  font-weight: 400;
  color: var(--text-2);
}
.dry {
  font-size: 11px;
}
.detail {
  color: var(--text-2);
  font-size: 12.5px;
  margin-top: 2px;
  overflow-wrap: anywhere;
}
.time {
  font-size: 12px;
  padding-top: 2px;
}
</style>
