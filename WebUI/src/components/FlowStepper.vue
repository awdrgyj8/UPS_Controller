<script setup>
import { computed } from 'vue'
import Icon from './Icon.vue'
import StatusPill from './StatusPill.vue'
import { clock, duration } from '../format.js'
import { store } from '../store.js'

const props = defineProps({
  sequence: { type: Object, default: null },
})

const PREVIEW = {
  kind: 'shutdown',
  title: '停電關機程序（尚未執行）',
  result: 'idle',
  steps: [
    { id: 'trigger', label: '觸發條件成立' },
    { id: 'list_servers', label: '取得面板伺服器清單' },
    { id: 'stop_servers', label: '送出伺服器停止訊號' },
    { id: 'wait_servers', label: '等待伺服器關機' },
    { id: 'shutdown_agents', label: '送出節點關機請求' },
    { id: 'save_state', label: '更新電源狀態為「關機」' },
  ].map((step) => ({ ...step, status: 'pending', detail: '', progress: null })),
}

const seq = computed(() => props.sequence || PREVIEW)
const RESULT = {
  running: { level: 'info', label: '執行中' },
  success: { level: 'good', label: '完成' },
  aborted: { level: 'critical', label: '中止' },
  idle: { level: 'neutral', label: '待命' },
}
const STEP = {
  pending: { icon: 'circle', cls: 'pending' },
  running: { icon: 'loader', cls: 'running' },
  done: { icon: 'check', cls: 'done' },
  warning: { icon: 'alert', cls: 'warn' },
  failed: { icon: 'x', cls: 'failed' },
  skipped: { icon: 'minus', cls: 'skipped' },
}
const elapsed = computed(() => {
  const s = seq.value
  if (!s.started_at) return ''
  return duration((s.finished_at || store.now) - s.started_at)
})
</script>

<template>
  <div class="flow">
    <div class="head">
      <strong>{{ seq.title }}</strong>
      <StatusPill :level="RESULT[seq.result].level" :label="RESULT[seq.result].label" />
      <span v-if="seq.started_at" class="muted when">{{ clock(seq.started_at) }} · {{ elapsed }}</span>
    </div>
    <ol>
      <li v-for="step in seq.steps" :key="step.id" :class="STEP[step.status]?.cls">
        <span class="marker"><Icon :name="STEP[step.status]?.icon || 'circle'" :size="12" :stroke="3" /></span>
        <div class="body">
          <div class="label">{{ step.label }}</div>
          <div v-if="step.detail" class="detail">{{ step.detail }}</div>
          <div v-if="step.progress != null && step.status === 'running'" class="progress">
            <div :style="{ width: Math.round(step.progress * 100) + '%' }"></div>
          </div>
        </div>
      </li>
    </ol>
    <div v-if="sequence && sequence.detail && sequence.result !== 'running'" class="result" :class="sequence.result">
      {{ sequence.detail }}
    </div>
  </div>
</template>

<style scoped>
.head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.when {
  font-size: 12px;
}
ol {
  list-style: none;
  margin: 0;
  padding: 0;
}
li {
  display: grid;
  grid-template-columns: 22px 1fr;
  gap: 10px;
  position: relative;
  padding-bottom: 12px;
  --c: var(--axis);
}
li:not(:last-child)::after {
  content: '';
  position: absolute;
  left: 10px;
  top: 22px;
  bottom: 0;
  width: 2px;
  background: var(--grid);
}
li.done::after {
  background: color-mix(in srgb, var(--good) 50%, var(--grid));
}
.marker {
  display: inline-grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--c);
  color: #fff;
  z-index: 1;
}
.pending .marker { background: var(--surface-2); color: var(--muted); border: 1px solid var(--border-strong); }
.running .marker { background: var(--info); }
.done .marker { background: var(--good); }
.warn .marker { background: var(--warning); color: #0b0b0b; }
.failed .marker { background: var(--critical); }
.skipped .marker { background: var(--surface-3); color: var(--muted); }
.label {
  font-weight: 500;
  padding-top: 1px;
}
.pending .label, .skipped .label {
  color: var(--muted);
}
.detail {
  font-size: 12px;
  color: var(--text-2);
  overflow-wrap: anywhere;
}
.progress {
  margin-top: 6px;
  height: 4px;
  border-radius: 4px;
  background: color-mix(in srgb, var(--info) 20%, var(--surface-2));
}
.progress div {
  height: 100%;
  border-radius: 4px;
  background: var(--info);
  transition: width 0.3s;
}
.result {
  font-size: 13px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--surface-2);
}
.result.success { background: color-mix(in srgb, var(--good) 12%, var(--surface)); }
.result.aborted { background: color-mix(in srgb, var(--critical) 12%, var(--surface)); }
</style>
