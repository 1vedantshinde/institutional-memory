import { forwardRef } from 'react'
import { cn } from '../../lib/utils'

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {}

export const Input = forwardRef<HTMLInputElement, InputProps>(({ className, ...props }, ref) => (
  <input
    ref={ref}
    className={cn(
      'flex h-8 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-1 text-sm text-[var(--text)] placeholder:text-[var(--muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:border-[var(--accent)] disabled:opacity-40 font-[var(--font-sans)]',
      className,
    )}
    {...props}
  />
))
Input.displayName = 'Input'
