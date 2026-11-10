// 幾個頁面共用的 SVG 路徑

// 市電的正弦波（寬 440、四個週期）：供電時是波形，停電時是一條平線。mid 是中線的 y，amp 是振幅。
export function sinePath(flat, mid = 46, amp = 24) {
  let d = ''
  for (let x = -4; x <= 444; x += 4) {
    d += `${d ? 'L' : 'M'}${x} ${(mid + (flat ? 0 : Math.sin((x / 440) * Math.PI * 8) * amp)).toFixed(1)}`
  }
  return d
}
