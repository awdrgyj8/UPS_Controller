<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { clock } from '../format.js'

const props = defineProps({
  samples: { type: Array, default: () => [] }, // [{ t, v }]
  unit: { type: String, default: '' },
  color: { type: String, default: 'var(--accent)' },
  min: { type: Number, default: null },
  max: { type: Number, default: null },
  threshold: { type: Object, default: null }, // { value, label }
  height: { type: Number, default: 170 },
  windowSec: { type: Number, default: 900 },
  now: { type: Number, required: true },
  format: { type: Function, default: null },
  label: { type: String, default: '' },
})

const root = ref(null)
const clipId = `clip-${Math.random().toString(36).slice(2, 10)}`
const width = ref(600)
const hover = ref(null)
let observer = null

onMounted(() => {
  observer = new ResizeObserver(([entry]) => {
    width.value = Math.max(240, Math.floor(entry.contentRect.width))
  })
  observer.observe(root.value)
})
onBeforeUnmount(() => observer?.disconnect())

const M = { l: 44, r: 56, t: 12, b: 24 }
const plotW = computed(() => width.value - M.l - M.r)
const plotH = computed(() => props.height - M.t - M.b)
const x0 = computed(() => props.now - props.windowSec)

const visible = computed(() => props.samples.filter((s) => s.t >= x0.value - 5))
const values = computed(() => visible.value.map((s) => s.v).filter((v) => v !== null && v !== undefined))

function niceStep(raw) {
  const exp = Math.pow(10, Math.floor(Math.log10(raw)))
  const f = raw / exp
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * exp
}

const yDomain = computed(() => {
  let lo = props.min
  let hi = props.max
  if (lo === null || hi === null) {
    const vs = values.value.length ? values.value : [0, 1]
    const vmin = Math.min(...vs)
    const vmax = Math.max(...vs)
    const pad = Math.max((vmax - vmin) * 0.15, Math.abs(vmax) * 0.02, 1)
    if (lo === null) lo = vmin - pad
    if (hi === null) hi = vmax + pad
  }
  const step = niceStep((hi - lo) / 4 || 1)
  lo = Math.floor(lo / step) * step
  hi = Math.ceil(hi / step) * step
  if (props.min !== null) lo = Math.max(lo, props.min)
  if (props.max !== null) hi = Math.min(hi, props.max)
  return { lo, hi, step }
})

const yTicks = computed(() => {
  const { lo, hi, step } = yDomain.value
  const ticks = []
  for (let v = lo; v <= hi + step / 1000; v += step) ticks.push(Math.round(v * 1000) / 1000)
  return ticks
})

const xTicks = computed(() => {
  const w = props.windowSec
  const interval = w <= 300 ? 60 : w <= 900 ? 180 : w <= 1800 ? 300 : 600
  const ticks = []
  for (let t = Math.ceil(x0.value / interval) * interval; t <= props.now; t += interval) ticks.push(t)
  return ticks
})

const sx = (t) => M.l + ((t - x0.value) / props.windowSec) * plotW.value
const sy = (v) => {
  const { lo, hi } = yDomain.value
  return M.t + (1 - (v - lo) / (hi - lo || 1)) * plotH.value
}

// 依空值或過大間隔把資料切成數段，避免把斷線期間連起來
const segments = computed(() => {
  const gapLimit = Math.max(15, props.windowSec / 40)
  const result = []
  let current = []
  let prevT = null
  for (const s of visible.value) {
    const missing = s.v === null || s.v === undefined
    if (missing || (prevT !== null && s.t - prevT > gapLimit)) {
      if (current.length) result.push(current)
      current = []
    }
    if (!missing) current.push(s)
    prevT = s.t
  }
  if (current.length) result.push(current)
  return result
})

const linePaths = computed(() =>
  segments.value.map((seg) => seg.map((s, i) => `${i ? 'L' : 'M'}${sx(s.t).toFixed(1)},${sy(s.v).toFixed(1)}`).join('')),
)
const areaPaths = computed(() => {
  const base = sy(yDomain.value.lo)
  return segments.value
    .filter((seg) => seg.length > 1)
    .map((seg) => {
      const line = seg.map((s, i) => `${i ? 'L' : 'M'}${sx(s.t).toFixed(1)},${sy(s.v).toFixed(1)}`).join('')
      return `${line}L${sx(seg[seg.length - 1].t).toFixed(1)},${base}L${sx(seg[0].t).toFixed(1)},${base}Z`
    })
})

const last = computed(() => {
  const seg = segments.value[segments.value.length - 1]
  return seg ? seg[seg.length - 1] : null
})

const fmt = (v) => (v === null || v === undefined ? '-' : props.format ? props.format(v) : `${Math.round(v * 10) / 10}${props.unit ? ' ' + props.unit : ''}`)
const tickFmt = (v) => (Math.abs(v) >= 10000 ? `${Math.round(v / 1000)}K` : `${v}`)

function onMove(event) {
  const rect = event.currentTarget.getBoundingClientRect()
  const x = ((event.clientX - rect.left) / rect.width) * width.value
  const t = x0.value + ((x - M.l) / plotW.value) * props.windowSec
  let best = null
  for (const s of visible.value) {
    if (s.v === null || s.v === undefined) continue
    if (!best || Math.abs(s.t - t) < Math.abs(best.t - t)) best = s
  }
  hover.value = best
}

const tooltipStyle = computed(() => {
  if (!hover.value) return {}
  const x = sx(hover.value.t)
  const flip = x > width.value * 0.65
  return {
    left: `${x}px`,
    top: `${sy(hover.value.v)}px`,
    transform: flip ? 'translate(calc(-100% - 12px), -50%)' : 'translate(12px, -50%)',
  }
})
</script>

<template>
  <div ref="root" class="chart" :style="{ height: height + 'px' }">
    <svg :width="width" :height="height" role="img" :aria-label="label"
         @mousemove="onMove" @mouseleave="hover = null">
      <defs>
        <clipPath :id="clipId">
          <rect :x="M.l" :y="M.t - 4" :width="plotW + 1" :height="plotH + 8" />
        </clipPath>
      </defs>
      <g class="grid">
        <line v-for="v in yTicks" :key="'g' + v" :x1="M.l" :x2="M.l + plotW" :y1="sy(v)" :y2="sy(v)" />
      </g>
      <line class="baseline" :x1="M.l" :x2="M.l + plotW" :y1="sy(yDomain.lo)" :y2="sy(yDomain.lo)" />
      <g class="axis">
        <text v-for="v in yTicks" :key="'y' + v" :x="M.l - 8" :y="sy(v) + 4" text-anchor="end">{{ tickFmt(v) }}</text>
        <text v-for="t in xTicks" :key="'x' + t" :x="sx(t)" :y="height - 6" text-anchor="middle">{{ clock(t, false) }}</text>
      </g>
      <g v-if="threshold" class="threshold">
        <line :x1="M.l" :x2="M.l + plotW" :y1="sy(threshold.value)" :y2="sy(threshold.value)" />
        <text :x="M.l + 6" :y="sy(threshold.value) - 5">{{ threshold.label }}</text>
      </g>
      <g :clip-path="`url(#${clipId})`">
        <path v-for="(d, i) in areaPaths" :key="'a' + i" :d="d" class="area" :style="{ fill: color }" />
        <path v-for="(d, i) in linePaths" :key="'l' + i" :d="d" class="line" :style="{ stroke: color }" />
      </g>
      <g v-if="last">
        <circle :cx="sx(last.t)" :cy="sy(last.v)" r="4" class="end" :style="{ fill: color }" />
        <text :x="sx(last.t) + 8" :y="sy(last.v) + 4" class="end-label">{{ fmt(last.v) }}</text>
      </g>
      <g v-if="hover">
        <line :x1="sx(hover.t)" :x2="sx(hover.t)" :y1="M.t" :y2="M.t + plotH" class="crosshair" />
        <circle :cx="sx(hover.t)" :cy="sy(hover.v)" r="5" class="end" :style="{ fill: color }" />
      </g>
      <rect :x="M.l" :y="0" :width="plotW" :height="height" fill="transparent" />
    </svg>
    <div v-if="hover" class="tooltip" :style="tooltipStyle">
      <div class="tt-time">{{ clock(hover.t) }}</div>
      <div class="tt-value"><span class="key" :style="{ background: color }"></span>{{ fmt(hover.v) }}</div>
    </div>
    <div v-if="!values.length" class="no-data">尚無資料</div>
  </div>
</template>

<style scoped>
.chart {
  position: relative;
  width: 100%;
}
svg {
  display: block;
  overflow: visible;
}
.grid line {
  stroke: var(--grid);
  stroke-width: 1;
}
.baseline {
  stroke: var(--axis);
  stroke-width: 1;
}
.axis text {
  fill: var(--muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.threshold line {
  stroke: var(--text-2);
  stroke-width: 1;
  stroke-dasharray: 4 4;
}
.threshold text {
  fill: var(--text-2);
  font-size: 11px;
  paint-order: stroke;
  stroke: var(--surface);
  stroke-width: 4px;
}
.line {
  fill: none;
  stroke-width: 2;
  stroke-linejoin: round;
  stroke-linecap: round;
}
.area {
  opacity: 0.1;
  stroke: none;
}
.end {
  stroke: var(--surface);
  stroke-width: 2;
}
.end-label {
  fill: var(--text);
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.crosshair {
  stroke: var(--axis);
  stroke-width: 1;
}
.tooltip {
  position: absolute;
  pointer-events: none;
  background: var(--surface-2);
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 12px;
  white-space: nowrap;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
  z-index: 2;
}
.tt-time {
  color: var(--muted);
}
.tt-value {
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
  font-variant-numeric: tabular-nums;
}
.key {
  width: 10px;
  height: 3px;
  border-radius: 2px;
}
.no-data {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--muted);
  font-size: 13px;
  pointer-events: none;
}
</style>
