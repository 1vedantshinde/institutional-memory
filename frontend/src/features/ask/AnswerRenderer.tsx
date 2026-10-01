import { useState } from 'react'
import { AlertTriangle, ChevronDown, ChevronUp, FileText, RotateCcw, X } from 'lucide-react'
import { parseAnswerSegments, buildCitationMap } from '../../lib/citations'
import { parseAnswerBlocks, splitBold } from '../../lib/answerBlocks'
import { ChannelBadge } from '../../components/ChannelBadge'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from '../../components/ui/tooltip'
import type { Citation, DocumentSource } from '../../api/schemas'
import { cn } from '../../lib/utils'

interface CitationChipProps {
  label: string
  citation: Citation | undefined
  onClick: () => void
}

function CitationChip({ label, citation, onClick }: CitationChipProps) {
  const short = label.replace('Finding ', 'F')

  if (!citation) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono bg-[var(--surface-2)] text-[var(--muted)] border border-[var(--border)] cursor-help">
              {short}
              <AlertTriangle size={9} className="ml-1" />
            </span>
          </TooltipTrigger>
          <TooltipContent>No matching evidence returned for {label}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    )
  }

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            onClick={onClick}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono bg-[var(--accent-dim)] text-[var(--accent)] border border-[var(--accent)]/30 hover:bg-[var(--accent)]/20 transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--accent)]"
            aria-label={`View evidence for ${label}: ${citation.channel} ${citation.window_id}`}
          >
            {short}
          </button>
        </TooltipTrigger>
        <TooltipContent>
          <div className="space-y-0.5">
            <div>{citation.channel} · {citation.window_id}</div>
            <div className="text-[var(--muted)]">{citation.finding_id.slice(0, 20)}…</div>
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

const fileName = (path: string) => path.split('/').pop() ?? path

function SourceChip({ label, source, active, onClick }: { label: string; source: DocumentSource | undefined; active: boolean; onClick: () => void }) {
  const short = label.replace('Source ', 'S')
  if (!source) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono bg-[var(--surface-2)] text-[var(--muted)] border border-[var(--border)] cursor-help">
            {short}
            <AlertTriangle size={9} className="ml-1" />
          </span>
        </TooltipTrigger>
        <TooltipContent>No matching source returned for {label}</TooltipContent>
      </Tooltip>
    )
  }
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          onClick={onClick}
          aria-pressed={active}
          aria-label={`Show passage for ${label} from ${fileName(source.source_path)}`}
          className={cn(
            'inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono border transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--accent)]',
            active
              ? 'bg-[var(--accent)] text-[var(--bg)] border-[var(--accent)]'
              : 'bg-[var(--surface-2)] text-[var(--text)] border-[var(--border)] hover:border-[var(--accent)]/50',
          )}
        >
          <FileText size={9} />
          {short}
        </button>
      </TooltipTrigger>
      <TooltipContent>{fileName(source.source_path)}</TooltipContent>
    </Tooltip>
  )
}

interface AnswerRendererProps {
  answer: string
  citations: Citation[]
  /** Knowledge-document passages cited as [Source N] */
  sources?: DocumentSource[]
  findingCount: number
  onCitationClick: (citation: Citation) => void
}

export function AnswerRenderer({ answer, citations, sources = [], findingCount, onCitationClick }: AnswerRendererProps) {
  const [sourcesExpanded, setSourcesExpanded] = useState(true)
  const [openSource, setOpenSource] = useState<string | null>(null)
  const citationMap = buildCitationMap(citations)
  const sourceByLabel = new Map(sources.map((s) => [s.label, s]))
  const toggleSource = (label: string) => setOpenSource((cur) => (cur === label ? null : label))
  const shownSource = openSource ? sourceByLabel.get(openSource) : undefined

  // Inline content: **bold** runs and [Finding N] / [Source N] chips, as React text only
  const renderInline = (text: string) =>
    splitBold(text).map((run, r) => {
      const nodes = parseAnswerSegments(run.text).map((seg, i) => {
        if (seg.marker?.startsWith('Source ')) {
          return (
            <SourceChip
              key={i}
              label={seg.marker}
              source={sourceByLabel.get(seg.marker)}
              active={openSource === seg.marker}
              onClick={() => toggleSource(seg.marker!)}
            />
          )
        }
        if (seg.marker) {
          const idx = citationMap.get(seg.findingKey ?? '')
          const cit = idx !== undefined ? citations[idx] : undefined
          return (
            <CitationChip
              key={i}
              label={seg.marker}
              citation={cit}
              onClick={() => cit && onCitationClick(cit)}
            />
          )
        }
        return <span key={i}>{seg.text}</span>
      })
      return run.bold ? (
        <strong key={r} className="font-semibold">{nodes}</strong>
      ) : (
        <span key={r}>{nodes}</span>
      )
    })

  return (
    <div className="space-y-3">
      {/* Answer text with inline citation chips */}
      <div className="space-y-2 text-sm leading-relaxed text-[var(--text)]">
        {parseAnswerBlocks(answer).map((block, b) => {
          if (block.type === 'heading') {
            return (
              <p key={b} className="font-semibold text-[var(--text)] pt-1 first:pt-0">
                {renderInline(block.text)}
              </p>
            )
          }
          if (block.type === 'list') {
            return (
              <ul key={b} className="list-disc pl-5 space-y-1 marker:text-[var(--muted)]">
                {block.items.map((item, i) => <li key={i}>{renderInline(item)}</li>)}
              </ul>
            )
          }
          return <p key={b}>{renderInline(block.text)}</p>
        })}
      </div>

      {/* Finding count + sources */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          {findingCount > 0 || sources.length === 0 ? (
            <Badge variant="ok" className="text-[10px]">
              Grounded by {findingCount} finding{findingCount !== 1 ? 's' : ''}
            </Badge>
          ) : (
            <Badge variant="accent" className="text-[10px]">
              Answered from project documents
            </Badge>
          )}
          <button
            onClick={() => setSourcesExpanded((v) => !v)}
            className="flex items-center gap-1 text-[11px] text-[var(--muted)] hover:text-[var(--text)] transition-colors"
          >
            {sourcesExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            Sources
          </button>
        </div>

        {sourcesExpanded && citations.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {citations.map((c) => (
              <button
                key={c.finding_id}
                onClick={() => onCitationClick(c)}
                className="flex items-center gap-1.5 px-2 py-1 rounded-full text-[10px] font-mono border border-[var(--border)] bg-[var(--surface-2)] hover:bg-[var(--surface-2)]/80 text-[var(--text)] transition-colors"
                aria-label={`View evidence: ${c.label}`}
              >
                <span className="font-semibold text-[var(--accent)]">{c.label.replace('Finding ', 'F')}</span>
                <ChannelBadge channel={c.channel} size="sm" className="border-0 bg-transparent p-0" />
                <span className="text-[var(--muted)]">{c.window_id}</span>
              </button>
            ))}
          </div>
        )}

        {sourcesExpanded && sources.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {sources.map((s) => (
              <button
                key={s.label}
                onClick={() => toggleSource(s.label)}
                aria-pressed={openSource === s.label}
                className={cn(
                  'flex items-center gap-1.5 px-2 py-1 rounded-full text-[10px] font-mono border bg-[var(--surface-2)] text-[var(--text)] transition-colors',
                  openSource === s.label ? 'border-[var(--accent)]' : 'border-[var(--border)] hover:border-[var(--accent)]/50',
                )}
                aria-label={`Show passage: ${s.label}, ${fileName(s.source_path)}`}
              >
                <span className="font-semibold text-[var(--accent)]">{s.label.replace('Source ', 'S')}</span>
                <span className="text-[var(--muted)]">{fileName(s.source_path)}</span>
              </button>
            ))}
          </div>
        )}

        {shownSource && (
          <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3 text-xs" role="region" aria-label={`Passage for ${shownSource.label}`}>
            <div className="flex items-center justify-between gap-2 mb-1.5">
              <span className="flex items-center gap-1.5 font-medium text-[var(--text)]">
                <FileText size={12} className="text-[var(--accent)]" />
                {shownSource.label} · {fileName(shownSource.source_path)}
              </span>
              <button onClick={() => setOpenSource(null)} aria-label="Close passage" className="text-[var(--muted)] hover:text-[var(--text)]">
                <X size={12} />
              </button>
            </div>
            <blockquote className="border-l-2 border-[var(--accent)]/40 pl-2 text-[var(--muted)] leading-relaxed whitespace-pre-wrap">
              {shownSource.snippet}
            </blockquote>
          </div>
        )}
      </div>
    </div>
  )
}
