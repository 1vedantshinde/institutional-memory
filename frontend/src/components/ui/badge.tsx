import { cn } from '../../lib/utils'
import { cva, type VariantProps } from 'class-variance-authority'

const badgeVariants = cva(
  'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium font-mono transition-colors',
  {
    variants: {
      variant: {
        default: 'bg-[var(--surface-2)] text-[var(--text)] border border-[var(--border)]',
        accent: 'bg-[var(--accent-dim)] text-[var(--accent)] border border-[var(--accent)]/30',
        ok: 'bg-[var(--ok)]/15 text-[var(--ok)] border border-[var(--ok)]/30',
        warn: 'bg-[var(--warn)]/15 text-[var(--warn)] border border-[var(--warn)]/30',
        danger: 'bg-[var(--danger)]/15 text-[var(--danger)] border border-[var(--danger)]/30',
        muted: 'bg-[var(--surface-2)] text-[var(--muted)]',
      },
    },
    defaultVariants: { variant: 'default' },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}
