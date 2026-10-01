export type ChannelId =
  | 'Vib_Spindle'
  | 'Vib_Table'
  | 'X_Load_Cell'
  | 'Y_Load_Cell'
  | 'Z_Load_Cell'
  | 'Current'

export type AllChannelId = ChannelId | 'Time'

export const CHANNELS: ChannelId[] = [
  'Vib_Spindle',
  'Vib_Table',
  'X_Load_Cell',
  'Y_Load_Cell',
  'Z_Load_Cell',
  'Current',
]

export const CHANNEL_LABELS: Record<ChannelId, string> = {
  Vib_Spindle: 'Spindle Vibration',
  Vib_Table: 'Table Vibration',
  X_Load_Cell: 'X Load Cell',
  Y_Load_Cell: 'Y Load Cell',
  Z_Load_Cell: 'Z Load Cell',
  Current: 'Motor Current',
}

// CSS variable names that map to channel colors defined in index.css
export const CHANNEL_COLORS: Record<ChannelId, string> = {
  Vib_Spindle: 'var(--ch-vib-spindle)',
  Vib_Table: 'var(--ch-vib-table)',
  X_Load_Cell: 'var(--ch-x-load)',
  Y_Load_Cell: 'var(--ch-y-load)',
  Z_Load_Cell: 'var(--ch-z-load)',
  Current: 'var(--ch-current)',
}

// Tailwind-compatible hex fallbacks for Recharts (can't use CSS vars)
export const CHANNEL_HEX: Record<ChannelId, string> = {
  Vib_Spindle: '#60a5fa',
  Vib_Table: '#a78bfa',
  X_Load_Cell: '#f97316',
  Y_Load_Cell: '#fbbf24',
  Z_Load_Cell: '#34d399',
  Current: '#f472b6',
}

export function friendlyChannel(ch: string): string {
  return CHANNEL_LABELS[ch as ChannelId] ?? ch
}

export function isValidChannel(ch: string): ch is ChannelId {
  return CHANNELS.includes(ch as ChannelId)
}

// Map friendly words in natural language to canonical channel IDs
const CHANNEL_ALIASES: [RegExp, ChannelId][] = [
  [/spindle\s*vib/i, 'Vib_Spindle'],
  [/vib.*spindle/i, 'Vib_Spindle'],
  [/table\s*vib/i, 'Vib_Table'],
  [/vib.*table/i, 'Vib_Table'],
  [/x.*load/i, 'X_Load_Cell'],
  [/load.*x/i, 'X_Load_Cell'],
  [/y.*load/i, 'Y_Load_Cell'],
  [/load.*y/i, 'Y_Load_Cell'],
  [/z.*load/i, 'Z_Load_Cell'],
  [/load.*z/i, 'Z_Load_Cell'],
  [/current|motor/i, 'Current'],
]

export function detectChannel(text: string): ChannelId | null {
  for (const [re, ch] of CHANNEL_ALIASES) {
    if (re.test(text)) return ch
  }
  return null
}
