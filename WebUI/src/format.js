export function pad(n) {
  return String(n).padStart(2, '0')
}

export function clock(ts, withSeconds = true) {
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  const base = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  return withSeconds ? `${base}:${pad(d.getSeconds())}` : base
}

export function dateTime(ts) {
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${clock(ts)}`
}

export function duration(seconds, short = false) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '-'
  seconds = Math.max(0, Math.round(seconds))
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  const parts = []
  if (d) parts.push(`${d} 天`)
  if (h) parts.push(`${h} 小時`)
  if (m && (!short || !d)) parts.push(`${m} 分`)
  if (!d && !h && (s || !parts.length)) parts.push(`${s} 秒`)
  return parts.slice(0, short ? 2 : 3).join(' ')
}

export function ago(ts, now) {
  if (!ts) return '-'
  const diff = Math.max(0, (now ?? Date.now() / 1000) - ts)
  if (diff < 5) return '剛剛'
  if (diff < 60) return `${Math.round(diff)} 秒前`
  if (diff < 3600) return `${Math.round(diff / 60)} 分鐘前`
  if (diff < 86400) return `${Math.round(diff / 3600)} 小時前`
  return `${Math.round(diff / 86400)} 天前`
}

export function bytes(value) {
  if (value === null || value === undefined) return '-'
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let i = 0
  let v = value
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`
}

export function num(value, digits = 0, unit = '') {
  if (value === null || value === undefined || Number.isNaN(value)) return '-'
  return `${Number(value).toFixed(digits)}${unit ? ` ${unit}` : ''}`
}
