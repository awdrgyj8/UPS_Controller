import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { clock } from '../format.js'

function niceStep(raw) {
  const exp = Math.pow(10, Math.floor(Math.log10(raw)))
  const f = raw / exp
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * exp
}
const missing = (v) => v === null || v === undefined

// 時間序列折線圖。
//   samples：主要序列 [{ t, v }]；extra：疊在後面的細線 [{ samples, color, name }]
//   threshold：{ value, label } 畫一條虛線；windowSec：顯示最近多少秒
export default {
  name: 'LineChart',
  props: {
    samples: { type: Array, default: () => [] },
    extra: { type: Array, default: () => [] },
    name: { type: String, default: '' },
    unit: { type: String, default: '' },
    color: { type: String, default: 'var(--accent)' },
    min: { type: Number, default: null },
    max: { type: Number, default: null },
    threshold: { type: Object, default: null },
    height: { type: Number, default: 190 },
    windowSec: { type: Number, default: 900 },
    now: { type: Number, required: true },
    label: { type: String, default: '' },
  },
  setup(props) {
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

    const M = { l: 40, r: 12, t: 10, b: 26 }
    const plotW = computed(() => width.value - M.l - M.r)
    const plotH = computed(() => props.height - M.t - M.b)
    const x0 = computed(() => props.now - props.windowSec)
    const inWindow = (list) => list.filter((s) => s.t >= x0.value - 5)
    const visible = computed(() => inWindow(props.samples))
    const all = computed(() => [
      { samples: visible.value, color: props.color, name: props.name, main: true },
      ...props.extra.map((e) => ({ ...e, samples: inWindow(e.samples), main: false })),
    ])
    const values = computed(() => all.value.flatMap((s) => s.samples.map((p) => p.v)).filter((v) => !missing(v)))

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

    // 依空值或過大的間隔把資料切段，避免把斷線期間連成一條線
    function segmentsOf(samples) {
      const gapLimit = Math.max(15, props.windowSec / 40)
      const result = []
      let current = []
      let prevT = null
      for (const s of samples) {
        if (missing(s.v) || (prevT !== null && s.t - prevT > gapLimit)) {
          if (current.length) result.push(current)
          current = []
        }
        if (!missing(s.v)) current.push(s)
        prevT = s.t
      }
      if (current.length) result.push(current)
      return result
    }
    const toPath = (seg) => seg.map((s, i) => `${i ? 'L' : 'M'}${sx(s.t).toFixed(1)},${sy(s.v).toFixed(1)}`).join('')
    const drawn = computed(() =>
      all.value.map((series) => {
        const segments = segmentsOf(series.samples)
        const base = sy(yDomain.value.lo)
        return {
          ...series,
          lines: segments.map(toPath),
          areas: series.main
            ? segments
                .filter((seg) => seg.length > 1)
                .map((seg) => `${toPath(seg)}L${sx(seg[seg.length - 1].t).toFixed(1)},${base}L${sx(seg[0].t).toFixed(1)},${base}Z`)
            : [],
        }
      }),
    )

    const fmt = (v) => (missing(v) ? '-' : `${Math.round(v * 10) / 10}${props.unit ? ' ' + props.unit : ''}`)
    const tickFmt = (v) => (Math.abs(v) >= 10000 ? `${Math.round(v / 1000)}K` : `${v}`)

    function onMove(event) {
      const rect = event.currentTarget.getBoundingClientRect()
      const x = ((event.clientX - rect.left) / rect.width) * width.value
      const t = x0.value + ((x - M.l) / plotW.value) * props.windowSec
      let best = null
      for (const s of visible.value) {
        if (missing(s.v)) continue
        if (!best || Math.abs(s.t - t) < Math.abs(best.t - t)) best = s
      }
      hover.value = best
    }
    const tipStyle = computed(() => {
      if (!hover.value) return {}
      const x = sx(hover.value.t)
      const flip = x > width.value * 0.65
      return {
        left: `${x}px`,
        top: `${sy(hover.value.v)}px`,
        transform: flip ? 'translate(calc(-100% - 12px), -50%)' : 'translate(12px, -50%)',
      }
    })

    return { root, clipId, width, hover, M, plotW, plotH, yDomain, yTicks, xTicks, sx, sy, drawn, values, fmt, tickFmt, onMove, tipStyle, clock }
  },
  template: /* html */ `
    <div ref="root" class="chart" :style="{ height: height + 'px' }">
      <svg :width="width" :height="height" role="img" :aria-label="label" @mousemove="onMove" @mouseleave="hover = null">
        <defs>
          <clipPath :id="clipId"><rect :x="M.l" :y="M.t - 4" :width="plotW + 1" :height="plotH + 8" /></clipPath>
        </defs>
        <line v-for="v in yTicks" :key="'g' + v" class="c-grid" :x1="M.l" :x2="M.l + plotW" :y1="sy(v)" :y2="sy(v)" />
        <text v-for="v in yTicks" :key="'y' + v" :x="M.l - 10" :y="sy(v) + 4" text-anchor="end">{{ tickFmt(v) }}</text>
        <text v-for="t in xTicks" :key="'x' + t" :x="sx(t)" :y="height - 4" text-anchor="middle">{{ clock(t, false) }}</text>
        <g v-if="threshold" class="c-th">
          <line :x1="M.l" :x2="M.l + plotW" :y1="sy(threshold.value)" :y2="sy(threshold.value)" />
          <text :x="M.l + 6" :y="sy(threshold.value) + 16">{{ threshold.label }}</text>
        </g>
        <g :clip-path="'url(#' + clipId + ')'">
          <template v-for="(series, si) in drawn" :key="si">
            <path v-for="(d, i) in series.areas" :key="'a' + i" :d="d" class="c-area" :style="{ fill: series.color }" />
            <path v-for="(d, i) in series.lines" :key="'l' + i" :d="d" class="c-line" :class="{ thin: !series.main }"
                  :style="{ stroke: series.color }" />
          </template>
        </g>
        <g v-if="hover">
          <line class="c-cross" :x1="sx(hover.t)" :x2="sx(hover.t)" :y1="M.t" :y2="M.t + plotH" />
          <circle :cx="sx(hover.t)" :cy="sy(hover.v)" r="6" :style="{ fill: color }" />
        </g>
      </svg>
      <div v-if="hover" class="c-tip" :style="tipStyle"><span>{{ clock(hover.t) }}</span>{{ fmt(hover.v) }}</div>
      <div v-if="!values.length" class="c-none">還沒有資料</div>
    </div>`,
}
