import { computed, ref } from 'vue'
import { batteryLevel, store } from '../store.js'
import { clock, duration, num } from '../format.js'

const RANGES = [
  { label: '5 分', sec: 300 },
  { label: '15 分', sec: 900 },
  { label: '1 小時', sec: 3600 },
]
const GROUP_LABELS = {
  battery: '電池', input: '輸入', output: '輸出', ups: 'UPS', device: '裝置', driver: '驅動', ambient: '環境', outlet: '插座',
}
// NUT 變數分組的固定順序，沒列到的排在後面
const GROUP_ORDER = ['ups', 'battery', 'input', 'output', 'device', 'driver']

const clamp = (v) => Math.max(0, Math.min(100, v))

// UPS 數據頁：銘牌與狀態旗標、電池 / 負載 / 輸入 / 輸出 / 溫度、歷史趨勢、全部 NUT 變數
export default {
  name: 'UpsView',
  setup() {
    const s = computed(() => store.state)
    const ups = computed(() => s.value.ups)
    const vars = computed(() => ups.value.variables || {})
    const threshold = computed(() => s.value.settings.shutdown_battery_threshold)

    const model = computed(() => vars.value['ups.model'] || vars.value['device.model'] || 'UPS')
    const maker = computed(() => vars.value['ups.mfr'] || vars.value['device.mfr'] || '')
    const plate = computed(() =>
      [
        ['序號', vars.value['ups.serial'] || vars.value['device.serial']],
        ['韌體', vars.value['ups.firmware']],
        ['驅動', [vars.value['driver.name'], vars.value['driver.version']].filter(Boolean).join(' ')],
        ['自我測試', vars.value['ups.test.result']],
      ].filter(([, value]) => value),
    )

    const batteryClass = computed(() => {
      const level = batteryLevel(ups.value.battery, threshold.value)
      return level === 'good' ? '' : level
    })
    const batteryFacts = computed(() =>
      [
        ['續航', ups.value.runtime != null ? duration(ups.value.runtime) : ''],
        ['電壓', ups.value.battery_voltage != null ? num(ups.value.battery_voltage, 1, 'V') : ''],
        ['額定', vars.value['battery.voltage.nominal'] ? `${vars.value['battery.voltage.nominal']} V` : ''],
        ['種類', vars.value['battery.type']],
        ['製造', vars.value['battery.mfr.date']],
      ].filter(([, value]) => value),
    )
    const loadClass = computed(() => (ups.value.load >= 90 ? 'critical' : ups.value.load >= 75 ? 'warning' : ''))

    // 輸入電壓落在切換範圍的哪裡：超出範圍 UPS 就會改用電池
    const transfer = computed(() => {
      const lo = Number(vars.value['input.transfer.low'])
      const hi = Number(vars.value['input.transfer.high'])
      if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) return null
      const v = ups.value.input_voltage
      return { lo, hi, at: v != null && v > 0 ? clamp(((v - lo) / (hi - lo)) * 100) : null }
    })
    const mainsDown = computed(() => ups.value.ok === true && ups.value.power === false)

    const range = ref(900)
    const mode = ref('chart')
    const series = (key, scale = 1) =>
      store.history.map((sample) => ({ t: sample.t, v: sample[key] == null ? null : sample[key] * scale }))
    const charts = computed(() => [
      { key: 'battery', title: '電量', unit: '%', data: series('battery'), min: 0, max: 100,
        threshold: { value: threshold.value, label: `${threshold.value}% 關機` } },
      { key: 'load', title: '負載', unit: '%', data: series('load'), min: 0, max: 100 },
      { key: 'input', title: '輸入', unit: 'V', data: series('input_voltage'), min: 0, max: null },
      { key: 'runtime', title: '續航', unit: '分', data: series('runtime', 1 / 60), min: 0, max: null },
    ])
    const tableRows = computed(() => {
      const cutoff = store.now - range.value
      const rows = store.history.filter((sample) => sample.t >= cutoff)
      const step = Math.max(1, Math.ceil(rows.length / 60))
      return rows.filter((_, i) => i % step === 0).reverse()
    })

    const query = ref('')
    const groups = computed(() => {
      const q = query.value.trim().toLowerCase()
      const map = new Map()
      for (const [key, value] of Object.entries(vars.value).sort(([a], [b]) => a.localeCompare(b))) {
        if (q && !key.toLowerCase().includes(q) && !String(value).toLowerCase().includes(q)) continue
        const prefix = key.split('.')[0]
        if (!map.has(prefix)) map.set(prefix, [])
        map.get(prefix).push([key, value])
      }
      const rank = (prefix) => (GROUP_ORDER.includes(prefix) ? GROUP_ORDER.indexOf(prefix) : GROUP_ORDER.length)
      return [...map.entries()].sort(([a], [b]) => rank(a) - rank(b))
    })

    return {
      RANGES, GROUP_LABELS, store, ups, vars, threshold, model, maker, plate, batteryClass, batteryFacts, loadClass,
      transfer, mainsDown, range, mode, charts, tableRows, query, groups, clock, duration, num, clamp,
    }
  },
  template: /* html */ `
    <div class="v-ups">
      <div v-if="!ups.ok && ups.error" class="notice critical">{{ ups.error }}</div>

      <div class="grid">
        <section class="tile accent plate" aria-label="UPS">
          <div class="flags">
            <span v-for="flag in ups.status_flags" :key="flag.code" class="flag" :class="flag.level">
              <span class="dot"></span>{{ flag.code }} {{ flag.label }}
            </span>
            <span v-if="!ups.status_flags.length" class="flag critical"><span class="dot"></span>{{ ups.status }}</span>
          </div>
          <h2 class="model">{{ model }}</h2>
          <div v-if="maker" class="maker">{{ maker }}</div>
          <dl class="plate-facts">
            <div v-for="[name, value] in plate" :key="name"><dt>{{ name }}</dt><dd>{{ value }}</dd></div>
          </dl>
        </section>

        <section class="tile battery" :class="batteryClass" aria-label="電池">
          <div class="label">電量</div>
          <div class="big">{{ ups.battery ?? '-' }}<small>%</small></div>
          <div class="bar">
            <div class="meter" role="meter" :aria-valuenow="ups.battery" aria-valuemin="0" aria-valuemax="100" aria-label="電量">
              <i :style="{ width: clamp(ups.battery ?? 0) + '%' }"></i>
            </div>
            <span class="mark" :style="{ left: threshold + '%' }"><b>{{ threshold }}% 關機</b></span>
          </div>
          <dl class="kv">
            <template v-for="[name, value] in batteryFacts" :key="name"><dt>{{ name }}</dt><dd>{{ value }}</dd></template>
          </dl>
        </section>

        <section class="tile tint load" :class="loadClass" aria-label="負載">
          <div class="label">負載</div>
          <div class="big">{{ ups.load ?? '-' }}<small>%</small></div>
          <div class="meter" role="meter" :aria-valuenow="ups.load" aria-valuemin="0" aria-valuemax="100" aria-label="負載">
            <i :style="{ width: clamp(ups.load ?? 0) + '%' }"></i>
          </div>
          <div v-if="vars['ups.realpower']" class="watts">
            <b>{{ vars['ups.realpower'] }} W</b><span v-if="vars['ups.realpower.nominal']">/ {{ vars['ups.realpower.nominal'] }} W</span>
          </div>
        </section>

        <section class="tile temp" aria-label="溫度">
          <div class="label">溫度</div>
          <div class="big">{{ ups.temperature != null ? num(ups.temperature, 1) : '-' }}<small>°C</small></div>
        </section>

        <section class="tile deep feed-in" :class="{ down: mainsDown }" aria-label="輸入">
          <div class="label">輸入</div>
          <div class="reading">
            <div v-if="mainsDown" class="big">停電</div>
            <div v-else class="big">{{ ups.input_voltage != null ? num(ups.input_voltage, 1) : '-' }}<small>V</small></div>
            <div v-if="!mainsDown && ups.input_frequency != null" class="hz">{{ num(ups.input_frequency, 2) }} Hz</div>
          </div>
          <div v-if="transfer" class="window">
            <div class="track"><i v-if="transfer.at !== null" :style="{ left: transfer.at + '%' }"></i></div>
            <div class="ends"><span>{{ transfer.lo }} V</span><span>切換範圍</span><span>{{ transfer.hi }} V</span></div>
          </div>
        </section>

        <section class="tile feed-out" aria-label="輸出">
          <div class="label">輸出</div>
          <div class="reading">
            <div class="big">{{ ups.output_voltage != null ? num(ups.output_voltage, 1) : '-' }}<small>V</small></div>
            <div v-if="vars['output.frequency']" class="hz">{{ vars['output.frequency'] }} Hz</div>
          </div>
        </section>

        <section class="tile span-12 trend" aria-label="趨勢">
          <div class="tile-head">
            <div class="label">趨勢</div>
            <div class="tools">
              <div class="seg" role="group" aria-label="範圍">
                <button v-for="r in RANGES" :key="r.sec" :aria-pressed="range === r.sec" @click="range = r.sec">{{ r.label }}</button>
              </div>
              <div class="seg" role="group" aria-label="顯示方式">
                <button :aria-pressed="mode === 'chart'" @click="mode = 'chart'">圖表</button>
                <button :aria-pressed="mode === 'table'" @click="mode = 'table'">資料表</button>
              </div>
            </div>
          </div>
          <div v-if="mode === 'chart'" class="charts">
            <div v-for="chart in charts" :key="chart.key" class="cell">
              <h3>{{ chart.title }}<span>{{ chart.unit }}</span></h3>
              <LineChart :samples="chart.data" :now="store.now" :window-sec="range" :min="chart.min" :max="chart.max"
                         :unit="chart.unit" :threshold="chart.threshold || null" :height="180" :label="chart.title" />
            </div>
          </div>
          <div v-else class="table-wrap">
            <table class="table">
              <thead>
                <tr><th>時間</th><th>供電</th><th class="num">電量 %</th><th class="num">負載 %</th><th class="num">輸入 V</th><th class="num">輸出 V</th><th class="num">續航</th></tr>
              </thead>
              <tbody>
                <tr v-for="row in tableRows" :key="row.seq">
                  <td>{{ clock(row.t) }}</td>
                  <td>{{ row.power === true ? '市電' : row.power === false ? '電池' : '-' }}</td>
                  <td class="num">{{ row.battery ?? '-' }}</td>
                  <td class="num">{{ row.load ?? '-' }}</td>
                  <td class="num">{{ num(row.input_voltage, 1) }}</td>
                  <td class="num">{{ num(row.output_voltage, 1) }}</td>
                  <td class="num">{{ duration(row.runtime, true) }}</td>
                </tr>
              </tbody>
            </table>
            <div v-if="!tableRows.length" class="empty">還沒有資料</div>
          </div>
        </section>

        <section class="tile span-12 nut" data-testid="nut-variables" aria-label="NUT 變數">
          <div class="tile-head">
            <div class="label">NUT 變數</div>
            <input v-model="query" class="input" type="search" placeholder="搜尋" aria-label="搜尋 NUT 變數" data-testid="nut-search" />
          </div>
          <div class="groups">
            <div v-for="[prefix, items] in groups" :key="prefix" class="group">
              <h3>{{ GROUP_LABELS[prefix] || prefix }}</h3>
              <dl>
                <div v-for="[key, value] in items" :key="key" :data-var="key"><dt class="mono">{{ key }}</dt><dd>{{ value }}</dd></div>
              </dl>
            </div>
          </div>
          <div v-if="!groups.length" class="empty">沒有符合的變數</div>
        </section>
      </div>
    </div>`,
}
