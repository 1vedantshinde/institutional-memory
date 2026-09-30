import { cn } from '../lib/utils'

interface StatusDotProps {
  online: boolean | null // null = checking
  label: string
  className?: string
}

export function StatusDot({ online, label, className }: StatusDotProps) {
  return (
    <div className={cn('flex items-center gap-1.5', className)} title={`${label}: ${online === null ? 'checking…' : online ? 'online' : 'offline'}`}>
      <span
        className={cn(
          'w-2 h-2 rounded-full shrink-0 transition-colors',
          online === null ? 'bg-[var(--muted)] animate-pulse' : online ? 'bg-[var(--ok)]' : 'bg-[var(--danger)]',
        )}
        aria-hidden="true"
      />
      <span className="text-[11px] text-[var(--muted)] font-mono">{label}</span>
    </div>
  )
}
