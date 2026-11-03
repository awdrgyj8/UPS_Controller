<script setup>
import Icon from './Icon.vue'
import { clock } from '../format.js'

defineProps({
  events: { type: Array, default: () => [] },
  dense: { type: Boolean, default: false },
})

// 訊息開頭的表情符號與左側圖示重複，顯示時移除
const clean = (message) => message.replace(/^(?:✅|❌|⚠️|⚠|⌛|▶)\s*/u, '')

const ICON = { error: 'x', warning: 'alert', success: 'check', info: 'info' }
const SOURCES = {
  controller: '控制器', nut: 'NUT', ptero: '面板', agent: 'Agent', wol: 'WOL', web: '介面', sim: '模擬', test: '測試',
  system: '系統',
}
</script>

<template>
  <ol class="events" :class="{ dense }">
    <li v-for="event in events" :key="event.id" :class="event.level">
      <span class="icon"><Icon :name="ICON[event.level] || 'info'" :size="12" :stroke="3" /></span>
      <span class="time tabular">{{ clock(event.ts) }}</span>
      <span class="source chip">{{ SOURCES[event.source] || event.source }}</span>
      <span class="message">{{ clean(event.message) }}</span>
    </li>
    <li v-if="!events.length" class="empty">尚無事件</li>
  </ol>
</template>

<style scoped>
.events {
  list-style: none;
  margin: 0;
  padding: 0;
  font-size: 13px;
}
.events li {
  display: grid;
  grid-template-columns: 18px 64px max-content 1fr;
  align-items: start;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px solid var(--border);
}
.events li:last-child {
  border-bottom: 0;
}
.events li.empty {
  display: block;
}
.dense li {
  padding: 4px 0;
}
.icon {
  display: inline-grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  margin-top: 1px;
  background: var(--neutral);
  color: #fff;
}
.error .icon { background: var(--critical); }
.warning .icon { background: var(--warning); color: #0b0b0b; }
.success .icon { background: var(--good); }
.info .icon { background: var(--surface-3); color: var(--text-2); }
.time {
  color: var(--muted);
  font-size: 12px;
  padding-top: 1px;
}
.source {
  font-size: 11px;
}
.message {
  min-width: 0;
  overflow-wrap: anywhere;
}
@media (max-width: 600px) {
  .events li {
    grid-template-columns: 18px 60px 1fr;
  }
  .source {
    display: none;
  }
}
</style>
