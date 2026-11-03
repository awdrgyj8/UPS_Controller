import { reactive } from 'vue'
import { api, post, streamUrl, ApiError } from './api.js'

const HISTORY_SECONDS = 3600

export const store = reactive({
  state: null,
  history: [],
  connected: false,
  needToken: false,
  error: '',
  toasts: [],
  now: Date.now() / 1000,
})

let source = null
let toastId = 0

export function toast(message, level = 'info') {
  const id = ++toastId
  store.toasts.push({ id, message, level })
  setTimeout(() => {
    const index = store.toasts.findIndex((t) => t.id === id)
    if (index >= 0) store.toasts.splice(index, 1)
  }, 4500)
}

/** 執行 API 動作並以 toast 顯示結果 */
export async function act(path, body, success) {
  try {
    const result = await post(path, body)
    if (success) toast(typeof success === 'function' ? success(result) : success, 'good')
    return result
  } catch (e) {
    toast(e.message, 'critical')
    if (e instanceof ApiError && e.status === 401) store.needToken = true
    return null
  }
}

export async function connect() {
  try {
    store.state = await api('/api/state')
    const { samples } = await api('/api/history?minutes=60')
    store.history = samples
    store.needToken = false
    store.error = ''
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      store.needToken = true
      return
    }
    store.error = e.message
  }
  if (source) source.close()
  source = new EventSource(streamUrl())
  source.addEventListener('open', () => {
    store.connected = true
  })
  source.addEventListener('error', () => {
    store.connected = false
  })
  source.addEventListener('state', (event) => {
    store.state = JSON.parse(event.data)
    store.connected = true
  })
  source.addEventListener('samples', (event) => {
    const samples = JSON.parse(event.data)
    const lastSeq = store.history.length ? store.history[store.history.length - 1].seq : 0
    for (const sample of samples) if (sample.seq > lastSeq) store.history.push(sample)
    const cutoff = Date.now() / 1000 - HISTORY_SECONDS
    let drop = 0
    while (drop < store.history.length && store.history[drop].t < cutoff) drop++
    if (drop) store.history.splice(0, drop)
  })
}

setInterval(() => {
  store.now = Date.now() / 1000
}, 1000)

// ---- 共用的狀態判讀 ----
export const PHASE_LEVEL = {
  starting: 'neutral',
  monitoring: 'good',
  on_battery: 'warning',
  shutdown: 'serious',
  nodes_off: 'neutral',
  waking: 'warning',
  nut_error: 'critical',
  paused: 'warning',
}

export function agentLevel(agent, expected) {
  if (agent.online) return { level: 'good', label: '在線' }
  if (expected === false) return { level: 'neutral', label: '已關機' }
  return { level: 'critical', label: '離線' }
}

export const SERVER_STATES = {
  running: { level: 'good', label: '運行中' },
  starting: { level: 'warning', label: '啟動中' },
  stopping: { level: 'warning', label: '關閉中' },
  offline: { level: 'neutral', label: '已停止' },
  unknown: { level: 'critical', label: '未知' },
}

export function serverLevel(state) {
  return SERVER_STATES[state] || SERVER_STATES.unknown
}

// 面板回報 starting 但已運行超過 1 小時，視為運行中
// （常見於面板偵測不到「啟動完成」訊息的程式，例如 Discord Bot）。只影響顯示，不影響關機流程。
export const STARTING_AS_RUNNING_MS = 60 * 60 * 1000

export function serverStatus(server) {
  if (server.state === 'starting' && (server.uptime_ms || 0) >= STARTING_AS_RUNNING_MS) {
    return { ...SERVER_STATES.running, assumed: true }
  }
  return { ...serverLevel(server.state), assumed: false }
}

export const isServerRunning = (server) => serverStatus(server).level === 'good'

export function powerLevel(ups) {
  if (ups.ok !== true) return { level: 'critical', label: '無法讀取' }
  if (ups.power) return { level: 'good', label: '市電供電' }
  return { level: 'serious', label: '電池供電' }
}

export function batteryLevel(battery, threshold) {
  if (battery === null || battery === undefined) return 'neutral'
  if (battery <= threshold) return 'critical'
  if (battery <= threshold + 20) return 'warning'
  return 'good'
}

export const TEST_STATUS = {
  pass: { level: 'good', label: '通過', icon: 'check' },
  warn: { level: 'warning', label: '警告', icon: 'alert' },
  fail: { level: 'critical', label: '失敗', icon: 'x' },
  skip: { level: 'neutral', label: '略過', icon: 'minus' },
  running: { level: 'info', label: '執行中', icon: 'loader' },
  pending: { level: 'neutral', label: '等待', icon: 'circle' },
  cancelled: { level: 'warning', label: '已停止', icon: 'minus' },
}
