import { CHANNEL_LABELS, CHANNEL_COLORS, type ChannelId } from '../lib/channels'
import { cn } from '../lib/utils'

interface ChannelBadgeProps {
  channel: string
  className?: string
  size?: 'sm' | 'md'
}

export function ChannelBadge({ channel, className, size = 'sm' }: ChannelBadgeProps) {
  const color = CHANNEL_COLORS[channel as ChannelId] ?? 'var(--muted)'
  const label = CHANNEL_LABELS[channel as ChannelId] ?? channel

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2 font-mono font-medium border',
        size === 'sm' ? 'py-0.5 text-[11px]' : 'py-1 text-xs',
        className,
      )}
      style={{
        color,
        borderColor: color,
        backgroundColor: `color-mix(in srgb, ${color} 12%, transparent)`,
      }}
    >
      <span
        className="inline-block w-1.5 h-1.5 rounded-full shrink-0"
        style={{ backgroundColor: color }}
      />
      {label}
    </span>
  )
}
