/** Format a number with fixed decimal places using tabular numerals */
export function fmtNum(n: number, decimals = 3): string {
  return n.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
    useGrouping: false,
  })
}

export function fmtInt(n: number): string {
  return n.toLocaleString('en-US', { maximumFractionDigits: 0 })
}

export function fmtPercent(n: number, decimals = 1): string {
  return `${(n * 100).toFixed(decimals)}%`
}

export function fmtDuration(ms: number): string {
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const rem = s % 60
  return `${m}m ${rem}s`
}

export function fmtTimestamp(date: Date): string {
  return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}

export function fmtSampleRange(start: number, end: number): string {
  return `${fmtInt(start)} → ${fmtInt(end)} (${fmtInt(end - start)} samples)`
}

export function fmtTimeRange(start: number, end: number): string {
  return `${fmtNum(start, 4)} s → ${fmtNum(end, 4)} s (${fmtNum(end - start, 4)} s duration)`
}
