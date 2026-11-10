import { computed } from 'vue'
import { clock, duration } from '../format.js'
import { cleanMessage, store } from '../store.js'

// 還沒跑過任何流程時，顯示關機流程會經過哪些步驟
const PREVIEW = {
  kind: 'shutdown',
  title: '關機流程',
  result: 'idle',
  steps: ['條件成立', '取得伺服器清單', '停止伺服器', '等伺服器停止', '關閉節點', '記錄已關機'].map((label, i) => ({
    id: `preview-${i}`, label, status: 'pending', detail: '', progress: null,
  })),
}
const RESULT = {
  running: { level: 'info', label: '執行中' },
  success: { level: 'good', label: '完成' },
  aborted: { level: 'critical', label: '中止' },
  idle: { level: 'neutral', label: '待命' },
}
const STEP = {
  pending: { icon: '', cls: 'pending' },
  running: { icon: 'loader', cls: 'running' },
  done: { icon: 'check', cls: 'done' },
  warning: { icon: 'alert', cls: 'warn' },
  failed: { icon: 'x', cls: 'failed' },
  skipped: { icon: 'minus', cls: 'skipped' },
}

// 關機 / 喚醒流程的逐步進度
export default {
  name: 'FlowStepper',
  props: {
    sequence: { type: Object, default: null },
  },
  setup(props) {
    const seq = computed(() => props.sequence || PREVIEW)
    const result = computed(() => RESULT[seq.value.result] || RESULT.idle)
    const when = computed(() => {
      const s = seq.value
      if (!s.started_at) return ''
      return `${clock(s.started_at)}，${duration((s.finished_at || store.now) - s.started_at)}`
    })
    const stepOf = (step) => STEP[step.status] || STEP.pending
    return { seq, result, when, stepOf, cleanMessage }
  },
  template: /* html */ `
    <div class="flow">
      <div class="tile-head">
        <div class="label">{{ seq.title }}</div>
        <StatusPill :level="result.level" :label="result.label" />
      </div>
      <div v-if="when" class="aside" style="margin-top: 4px">{{ when }}</div>
      <ol class="steps" style="margin-top: 16px">
        <li v-for="step in seq.steps" :key="step.id" :class="stepOf(step).cls">
          <span class="mark"><Icon v-if="stepOf(step).icon" :name="stepOf(step).icon" :size="14" :stroke="3" /></span>
          <div class="body">
            <div>{{ step.label }}</div>
            <div v-if="step.detail" class="detail">{{ cleanMessage(step.detail) }}</div>
            <div v-if="step.progress != null && step.status === 'running'" class="meter">
              <i :style="{ width: Math.round(step.progress * 100) + '%' }"></i>
            </div>
          </div>
        </li>
      </ol>
      <div v-if="sequence && sequence.detail && sequence.result !== 'running'" class="notice"
           :class="sequence.result === 'success' ? 'good' : 'critical'" style="margin: 16px 0 0">
        {{ cleanMessage(sequence.detail) }}
      </div>
    </div>`,
}
