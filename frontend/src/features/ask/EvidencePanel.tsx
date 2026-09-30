import { useNavigate } from 'react-router-dom'
import { X, ExternalLink, AlertCircle } from 'lucide-react'
import type { Citation } from '../../api/schemas'
import { ProvenanceTrail } from './ProvenanceTrail'
import { ChannelBadge } from '../../components/ChannelBadge'
import { CopyButton } from '../../components/CopyButton'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { fmtSampleRange, fmtTimeRange, fmtInt } from '../../lib/format'
import { parsePath } from '../../lib/parsePath'
import { cn } from '../../lib/utils'
import { friendlyChannel } from '../../lib/channels'

interface EvidencePanelProps {
  citation: Citation | null
  onClose: () => void
  onAskAbout?: (question: string) => void
  className?: string
  asSheet?: boolean // mobile bottom sheet mode
}

function RangeBar({ sampleStart, sampleEnd }: { sampleStart: number; sampleEnd: number }) {
  const totalApprox = sampleEnd * 1.5 // approximate — we don't know actual recording length
  const startPct = (sampleStart / totalApprox) * 100
  const widthPct = ((sampleEnd - sampleStart) / totalApprox) * 100

  return (
    <div className="space-y-1">
      <p className="text-[10px] text-[var(--muted)] uppercase tracking-wide">Position within recording (approximate)</p>
      <div className="relative h-3 bg-[var(--surface-2)] rounded-full overflow-hidden" aria-label={`Window at samples ${sampleStart}–${sampleEnd}`}>
        <div
          className="absolute top-0 h-full rounded-full bg-[var(--accent)]/70"
          style={{ left: `${startPct}%`, width: `${widthPct}%` }}
        />
      </div>
      <div className="flex justify-between text-[10px] text-[var(--muted)] font-mono">
        <span>0</span>
        <span>~{fmtInt(Math.round(totalApprox))}</span>
      </div>
    </div>
  )
}

export function EvidencePanel({ citation, onClose, onAskAbout, className, asSheet }: EvidencePanelProps) {
  if (!citation) return null

  const parsed = parsePath(citation.source_path)
  const citationJson = JSON.stringify(citation, null, 2)
  const hasTimeRange = citation.time_range != null

  const handleAskAbout = () => {
    const ch = friendlyChannel(citation.channel)
    const cond = parsed.conditionId ?? citation.source_path
    onAskAbout?.(`Explain the anomaly in ${ch} for condition ${cond}, window ${citation.window_id}`)
  }

  return (
    <aside
      className={cn(
        'flex flex-col bg-[var(--surface)] border-[var(--border)]',
        asSheet
          ? 'rounded-t-2xl border-t w-full max-h-[80vh]'
          : 'border-l w-[360px] shrink-0',
        'overflow-hidden',
        className,
      )}
      style={asSheet ? { animation: 'slideInUp 0.2s ease' } : { animation: 'slideInRight 0.2s ease' }}
      aria-label="Citation detail"
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2 p-4 border-b border-[var(--border)] shrink-0">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold">{citation.label}</span>
            <Badge variant="accent" className="text-[10px]">{citation.model_version}</Badge>
          </div>
          <div className="flex items-center gap-1 text-[11px] text-[var(--muted)] font-mono">
            <span>{citation.finding_id}</span>
            <CopyButton value={citation.finding_id} />
          </div>
        </div>
        <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close evidence panel">
          <X size={14} />
        </Button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        {/* Provenance trail */}
        <div>
          <p className="text-[10px] text-[var(--muted)] uppercase tracking-widest mb-2">Provenance</p>
          <ProvenanceTrail
            sourcePath={citation.source_path}
            windowId={citation.window_id}
            findingId={citation.finding_id}
          />
        </div>

        {/* Channel */}
        <div>
          <p className="text-[10px] text-[var(--muted)] uppercase tracking-widest mb-1.5">Channel</p>
          <ChannelBadge channel={citation.channel} size="md" />
        </div>

        {/* Source file */}
        <div>
          <p className="text-[10px] text-[var(--muted)] uppercase tracking-widest mb-1.5">Source file</p>
          <p className="text-sm font-medium mb-1">{parsed.basename}</p>
          <div className="flex items-start gap-1 bg-[var(--surface-2)] rounded-md p-2">
            <code className="text-[10px] font-mono text-[var(--muted)] break-all flex-1 leading-relaxed">
              {citation.source_path}
            </code>
            <CopyButton value={citation.source_path} />
          </div>
        </div>

        {/* Sample range */}
        <div>
          <p className="text-[10px] text-[var(--muted)] uppercase tracking-widest mb-1.5">Sample range</p>
          <p className="text-sm font-mono">
            {fmtSampleRange(citation.sample_range.sample_start, citation.sample_range.sample_end)}
          </p>
        </div>

        {/* Range bar */}
        <RangeBar
          sampleStart={citation.sample_range.sample_start}
          sampleEnd={citation.sample_range.sample_end}
        />

        {/* Time range */}
        <div>
          <p className="text-[10px] text-[var(--muted)] uppercase tracking-widest mb-1.5">Time range</p>
          {hasTimeRange ? (
            <p className="text-sm font-mono">
              {fmtTimeRange(citation.time_range!.time_start, citation.time_range!.time_end)}
            </p>
          ) : (
            <div className="flex items-center gap-1.5 text-[var(--warn)]">
              <AlertCircle size={13} />
              <span className="text-xs">Time range unavailable (sampling rate not confirmed)</span>
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex flex-col gap-2 pt-2 border-t border-[var(--border)]">
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigator.clipboard.writeText(citationJson).catch(() => {})}
            className="w-full"
          >
            Copy citation as JSON
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleAskAbout}
            className="w-full"
          >
            Ask about this window
          </Button>
        </div>
      </div>
    </aside>
  )
}
