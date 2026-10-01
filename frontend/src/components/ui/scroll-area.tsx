import * as RadixScrollArea from '@radix-ui/react-scroll-area'
import React from 'react'
import { cn } from '@/lib/utils'

export interface ScrollAreaProps
  extends React.ComponentPropsWithoutRef<typeof RadixScrollArea.Root> {}

export function ScrollArea({ className, children, ...props }: ScrollAreaProps) {
  return (
    <RadixScrollArea.Root
      className={cn('relative overflow-hidden', className)}
      {...props}
    >
      <RadixScrollArea.Viewport className="h-full w-full rounded-[inherit]">
        {children}
      </RadixScrollArea.Viewport>
      <ScrollBar />
      <RadixScrollArea.Corner />
    </RadixScrollArea.Root>
  )
}

export interface ScrollBarProps
  extends React.ComponentPropsWithoutRef<typeof RadixScrollArea.Scrollbar> {}

export function ScrollBar({
  className,
  orientation = 'vertical',
  ...props
}: ScrollBarProps) {
  return (
    <RadixScrollArea.Scrollbar
      orientation={orientation}
      className={cn(
        'select-none touch-none p-0.5 bg-transparent flex',
        orientation === 'vertical'
          ? 'h-full w-2 border-l border-l-transparent'
          : 'flex-col h-2 w-full border-t border-t-transparent',
        className,
      )}
      {...props}
    >
      <RadixScrollArea.Thumb className="bg-border rounded-full flex-1 relative" />
    </RadixScrollArea.Scrollbar>
  )
}
