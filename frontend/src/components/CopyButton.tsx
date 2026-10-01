import { useState } from 'react'
import { Copy, Check } from 'lucide-react'
import { Button } from './ui/button'
import { cn } from '../lib/utils'

interface CopyButtonProps {
  value: string
  className?: string
  size?: 'sm' | 'icon-sm'
}

export function CopyButton({ value, className, size = 'icon-sm' }: CopyButtonProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {}
  }

  return (
    <Button
      variant="ghost"
      size={size}
      onClick={handleCopy}
      aria-label={copied ? 'Copied' : 'Copy to clipboard'}
      className={cn('text-[var(--muted)] hover:text-[var(--text)]', className)}
    >
      {copied ? <Check size={12} className="text-[var(--ok)]" /> : <Copy size={12} />}
    </Button>
  )
}
