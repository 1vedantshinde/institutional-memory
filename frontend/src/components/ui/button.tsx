import { forwardRef } from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '../../lib/utils'

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-1 disabled:pointer-events-none disabled:opacity-40 select-none cursor-pointer',
  {
    variants: {
      variant: {
        default: 'bg-[var(--accent)] text-[var(--bg)] hover:bg-[var(--accent)]/90',
        outline: 'border border-[var(--border)] bg-transparent text-[var(--text)] hover:bg-[var(--surface-2)]',
        ghost: 'bg-transparent text-[var(--text)] hover:bg-[var(--surface-2)]',
        danger: 'bg-[var(--danger)] text-white hover:bg-[var(--danger)]/90',
        muted: 'bg-[var(--surface-2)] text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)]/80',
      },
      size: {
        sm: 'h-7 px-3 text-xs',
        md: 'h-8 px-4',
        lg: 'h-10 px-5 text-sm',
        icon: 'h-8 w-8 p-0',
        'icon-sm': 'h-6 w-6 p-0',
      },
    },
    defaultVariants: { variant: 'default', size: 'md' },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button'
    return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
  },
)
Button.displayName = 'Button'
