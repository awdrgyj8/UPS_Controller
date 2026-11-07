<script setup>
import { computed, ref } from 'vue'
import StatusPill from '../components/StatusPill.vue'
import StatTile from '../components/StatTile.vue'
import LineChart from '../components/LineChart.vue'
import { batteryLevel, loadSubText, powerLevel, store, wattsText } from '../store.js'
import { ago, clock, duration, num } from '../format.js'

const s = computed(() => store.state)
const ups = computed(() => s.value.ups)
const vars = computed(() => ups.value.variables || {})
const threshold = computed(() => s.value.settings.shutdown_battery_threshold)

const RANGES = [
  { label: '5 分鐘', sec: 300 },
  { label: '15 分鐘', sec: 900 },
  { label: '1 小時', sec: 3600 },
]
const range = ref(900)
const view = ref('chart')

const series = (key, scale = 1) =>
  store.history.map((sample) => ({ t: sample.t, v: sample[key] == null ? null : sample[key] * scale }))

const CHARTS = computed(() => [
  { key: 'battery', title: '電池電量', unit: '%', data: series('battery'), min: 0, max: 100,
    threshold: { value: threshold.value, label: `關機門檻 ${threshold.value}%` } },
  { key: 'realpower', title: ups.value.realpower_estimated ? '負載功率（估算）' : '負載功率', unit: 'W',
    data: series('realpower'), min: 0, max: ups.value.realpower_nominal || null },
  { key: 'load', title: 'UPS 負載', unit: '%', data: series('load'), min: 0, max: 100 },
  { key: 'runtime', title: '預估續航', unit: '分鐘', data: series('runtime', 1 / 60), min: 0, max: null,
    format: (v) => `${v.toFixed(1)} 分` },
  { key: 'input', title: '輸入電壓', unit: 'V', data: series('input_voltage'), min: 0, max: null },
  { key: 'battery_voltage', title: '電池電壓', unit: 'V', data: series('battery_voltage'), min: null, max: null },
])

const tableRows = computed(() => {
  const cutoff = store.now - range.value
  const rows = store.history.filter((sample) => sample.t >= cutoff)
  const step = Math.max(1, Math.ceil(rows.length / 60))
  return rows.filter((_, i) => i % step === 0).reverse()
})

// NUT 變數表
const query = ref('')
const GROUP_LABELS = {
  battery: '電池 battery.*', input: '輸入 input.*', output: '輸出 output.*', ups: 'UPS ups.*',
  device: '裝置 device.*', driver: '驅動程式 driver.*', ambient: '環境 ambient.*', outlet: '插座 outlet.*',
}
const groups = computed(() => {
  const q = query.value.trim().toLowerCase()
  const map = new Map()
  for (const [key, value] of Object.entries(vars.value).sort(([a], [b]) => a.localeCompare(b))) {
    if (q && !key.toLowerCase().includes(q) && !String(value).toLowerCase().includes(q)) continue
    const prefix = key.split('.')[0]
    if (!map.has(prefix)) map.set(prefix, [])
    map.get(prefix).push([key, value])
  }
  return [...map.entries()]
})

const DESCRIPTIONS = {
  'battery.charge': '電池電量 (%)',
  'battery.charge.low': '低電量判定 (%)',
  'battery.charge.warning': '電量警告 (%)',
  'battery.runtime': '預估續航 (秒)',
  'battery.runtime.low': '低續航判定 (秒)',
  'battery.voltage': '電池電壓 (V)',
  'battery.voltage.nominal': '電池額定電壓 (V)',
  'battery.type': '電池種類',
  'battery.mfr.date': '電池製造日期',
  'input.voltage': '輸入電壓 (V)',
  'input.voltage.nominal': '額定輸入電壓 (V)',
  'input.frequency': '輸入頻率 (Hz)',
  'input.transfer.low': '低電壓切換點 (V)',
  'input.transfer.high': '高電壓切換點 (V)',
  'output.voltage': '輸出電壓 (V)',
  'output.frequency': '輸出頻率 (Hz)',
  'ups.status': 'UPS 狀態旗標',
  'ups.load': '負載 (%)',
  'ups.realpower': '實際功率 (W)',
  'ups.realpower.nominal': '額定功率 (W)',
  'ups.power.nominal': '額定容量 (VA)',
  'ups.temperature': 'UPS 溫度 (°C)',
  'ups.beeper.status': '蜂鳴器',
  'ups.test.result': '自我測試結果',
  'ups.delay.shutdown': '關機延遲 (秒)',
  'ups.timer.shutdown': '關機倒數 (秒)',
  'ups.firmware': '韌體版本',
}
</script>

<template>
  <div class="grid">
    <section class="card">
      <div class="card-body header">
        <div>
          <h2>{{ vars['ups.model'] || vars['device.model'] || 'UPS' }}</h2>
          <div class="muted">
            {{ vars['ups.mfr'] || vars['device.mfr'] || '-' }} · 序號 <span class="mono">{{ vars['ups.serial'] || vars['device.serial'] || '-' }}</span>
            · 韌體 {{ vars['ups.firmware'] || '-' }} · {{ vars['driver.name'] || '-' }} {{ vars['driver.version'] || '' }}
          </div>
        </div>
        <span class="spacer"></span>
        <StatusPill size="lg" v-bind="powerLevel(ups)" />
      </div>
      <div class="card-body flags">
        <span class="muted small">ups.status =</span>
        <code class="mono">{{ ups.status }}</code>
        <StatusPill v-for="flag in ups.status_flags" :key="flag.code" :level="flag.level" :label="`${flag.code} ${flag.label}`" />
        <span class="spacer"></span>
        <span class="muted small">更新於 {{ ago(ups.updated_at, store.now) }}（每 {{ s.settings.monitor_interval }} 秒）</span>
      </div>
      <div v-if="!ups.ok && ups.error" class="card-body"><div class="notice critical">{{ ups.error }}</div></div>
    </section>

    <section class="tiles">
      <StatTile label="電池電量" :value="ups.battery != null ? ups.battery + '%' : '-'" :level="batteryLevel(ups.battery, threshold)"
                :sub="`低電量 ${vars['battery.charge.low'] || '-'}% · 關機門檻 ${threshold}%`" />
      <StatTile label="預估續航" :value="duration(ups.runtime, true)" :sub="`低續航 ${duration(Number(vars['battery.runtime.low']), true)}`" />
      <StatTile label="電池電壓" :value="num(ups.battery_voltage, 1, 'V')" :sub="`額定 ${vars['battery.voltage.nominal'] || '-'} V · ${vars['battery.type'] || ''}`" />
      <StatTile label="負載功率" :value="ups.realpower != null ? wattsText(ups) : ups.load != null ? ups.load + '%' : '-'"
                :sub="loadSubText(ups) || '-'" />
      <StatTile label="輸入" :value="num(ups.input_voltage, 1, 'V')" :sub="`${num(ups.input_frequency, 2, 'Hz')} · 切換 ${vars['input.transfer.low'] || '-'}–${vars['input.transfer.high'] || '-'} V`" />
      <StatTile label="輸出" :value="num(ups.output_voltage, 1, 'V')" :sub="`${vars['output.frequency'] || '-'} Hz`" />
      <StatTile label="溫度" :value="num(ups.temperature, 1, '°C')" :sub="`自我測試：${vars['ups.test.result'] || '-'}`" />
      <StatTile label="電池製造日期" :value="vars['battery.mfr.date'] || '-'" :sub="`蜂鳴器 ${vars['ups.beeper.status'] || '-'}`" />
    </section>

    <section class="card">
      <div class="card-header">
        <h2 class="card-title">歷史趨勢</h2>
        <span class="card-sub">記憶體中保留最近 1 小時</span>
        <span class="spacer"></span>
        <div class="segmented">
          <button v-for="r in RANGES" :key="r.sec" :class="{ active: range === r.sec }" @click="range = r.sec">{{ r.label }}</button>
        </div>
        <div class="segmented">
          <button :class="{ active: view === 'chart' }" @click="view = 'chart'">圖表</button>
          <button :class="{ active: view === 'table' }" @click="view = 'table'">資料表</button>
        </div>
      </div>
      <div v-if="view === 'chart'" class="card-body charts">
        <div v-for="chart in CHARTS" :key="chart.key" class="chart-cell">
          <h3>{{ chart.title }} <span class="muted">· {{ chart.unit }}</span></h3>
          <LineChart :samples="chart.data" :now="store.now" :window-sec="range" :min="chart.min" :max="chart.max"
                     :unit="chart.unit" :threshold="chart.threshold || null" :format="chart.format || null" :label="chart.key" />
        </div>
      </div>
      <div v-else class="card-body table-wrap">
        <table class="table">
          <thead>
            <tr><th>時間</th><th>市電</th><th class="num">電量 %</th><th class="num">負載 %</th><th class="num">功率 W</th><th class="num">輸入 V</th><th class="num">輸出 V</th><th class="num">續航</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in tableRows" :key="row.seq">
              <td class="tabular">{{ clock(row.t) }}</td>
              <td>{{ row.power === true ? '正常' : row.power === false ? '電池' : '—' }}</td>
              <td class="num">{{ row.battery ?? '—' }}</td>
              <td class="num">{{ row.load ?? '—' }}</td>
              <td class="num">{{ row.realpower ?? '—' }}</td>
              <td class="num">{{ num(row.input_voltage, 1) }}</td>
              <td class="num">{{ num(row.output_voltage, 1) }}</td>
              <td class="num">{{ duration(row.runtime, true) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="card">
      <div class="card-header">
        <h2 class="card-title">全部 NUT 變數</h2>
        <span class="card-sub">{{ Object.keys(vars).length }} 個 · {{ s.nut.host }}:{{ s.nut.port }} / {{ s.nut.ups_name }}</span>
        <span class="spacer"></span>
        <input v-model="query" class="input" type="search" placeholder="搜尋變數或數值…" />
      </div>
      <div class="card-body var-groups">
        <div v-for="[prefix, items] in groups" :key="prefix" class="var-group">
          <h4 class="section-title">{{ GROUP_LABELS[prefix] || prefix + '.*' }}</h4>
          <table class="table">
            <tbody>
              <tr v-for="[key, value] in items" :key="key">
                <td class="mono key">{{ key }}</td>
                <td class="mono value">{{ value }}</td>
                <td class="muted desc">{{ DESCRIPTIONS[key] || '' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="!groups.length" class="empty">沒有符合的變數</div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.header {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
h2 {
  margin: 0 0 2px;
  font-size: 18px;
}
.flags {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding-top: 0;
}
.small {
  font-size: 12px;
}
.charts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px 24px;
}
@media (max-width: 900px) {
  .charts {
    grid-template-columns: minmax(0, 1fr);
  }
}
.chart-cell h3 {
  font-size: 13px;
  font-weight: 600;
  margin: 0 0 6px;
}
.var-groups {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
  gap: 16px 24px;
}
@media (max-width: 600px) {
  .var-groups {
    grid-template-columns: minmax(0, 1fr);
  }
}
.key {
  white-space: nowrap;
}
.value {
  font-weight: 600;
  overflow-wrap: anywhere;
}
.desc {
  font-size: 12px;
}
</style>
