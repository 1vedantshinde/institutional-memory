import { useEffect, useState } from 'react'
import { Loader2, XCircle, Clock } from 'lucide-react'
import { Progress } from '../../components/ui/progress'
import { Button } from '../../components/ui/button'
import { ChannelBadge } from '../../components/ChannelBadge'
import { Badge } from '../../components/ui/badge'
import { fmtDuration } from '../../lib/format'
import type { AnalysingMeta } from './useChatFlow'

interface AnalysisProgressCardProps {
  meta: AnalysingMeta
  state: 'analysing' | 'resending' | 'timeout'
  elapsedMs: number
  onCancel: () => void
  onRetry: () => void
}

export function AnalysisProgressCard({ meta, state, elapsedMs, onCancel, onRetry }: AnalysisProgressCardProps) {
  if (state === 'timeout') {
    return (
      <div className="rounded-xl border border-[var(--warn)]/30 bg-[var(--warn)]/5 p-4 space-y-3">
        <div className="flex items-center gap-2 text-[var(--warn)]">
          <Clock size={15} />
          <span className="text-sm font-medium">Analysis timed out</span>
        </div>
        <p className="text-xs text-[var(--muted)]">
          Analysis is still running in the background. You can retry this question when it completes.
        </p>
        <Button size="sm" onClick={onRetry}>Retry question</Button>
      </div>
    )
  }

  return (
    <div
      className="rounded-xl border border-[var(--accent)]/20 bg-[var(--accent-dim)] p-4 space-y-3"
    >
      {/* Not a live region: the elapsed timer ticks every 500 ms. MessageList
          announces state changes through #live-announcer instead. */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Loader2 size={14} className="text-[var(--accent)] animate-spin" />
          <span className="text-sm font-medium text-[var(--accent)]">
            {state === 'resending'
              ? 'Retrieving answer…'
              : meta.phase === 'ingesting'
                ? 'Preparing DAQ inventory'
                : `Analysing condition ${meta.conditionId ?? ''}`}
          </span>
        </div>
        <span className="text-[11px] text-[var(--muted)] font-mono">{fmtDuration(elapsedMs)}</span>
      </div>

      <div className="flex items-center gap-2">
        {meta.channel && <ChannelBadge channel={meta.channel} size="sm" />}
        {meta.conditionId && <Badge variant="muted" className="text-[10px]">condition {meta.conditionId}</Badge>}
      </div>

      <Progress indeterminate />

      <p className="text-[11px] text-[var(--muted)]">{meta.message}</p>

      {state === 'analysing' && (
        <Button variant="ghost" size="sm" onClick={onCancel} className="text-[var(--muted)]">
          <XCircle size={13} />
          Cancel
        </Button>
      )}
    </div>
  )
}
