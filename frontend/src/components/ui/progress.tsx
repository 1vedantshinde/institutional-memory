import * as ProgressPrimitive from '@radix-ui/react-progress'
import { cn } from '../../lib/utils'

export function Progress({ className, value, indeterminate, ...props }: React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root> & { indeterminate?: boolean }) {
  return (
    <ProgressPrimitive.Root
      className={cn('relative h-1.5 w-full overflow-hidden rounded-full bg-[var(--surface-2)]', className)}
      {...props}
    >
      {indeterminate ? (
        <div
          className="absolute h-full w-1/3 rounded-full bg-[var(--accent)]"
          style={{ animation: 'indeterminate 1.5s ease-in-out infinite' }}
        />
      ) : (
        <ProgressPrimitive.Indicator
          className="h-full rounded-full bg-[var(--accent)] transition-all"
          style={{ transform: `translateX(-${100 - (value ?? 0)}%)` }}
        />
      )}
    </ProgressPrimitive.Root>
  )
}
