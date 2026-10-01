import { useEffect, useRef } from 'react'
import { prefersReducedMotion } from '../../lib/announce'
import { User, Bot, AlertCircle, RefreshCw, ChevronDown, Loader2 } from 'lucide-react'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { AnswerRenderer } from './AnswerRenderer'
import { AnalysisProgressCard } from './AnalysisProgressCard'
import type { ChatMessage } from '../../store/sessionStore'
import type { FlowState, AnalysingMeta, ErrorMeta } from './useChatFlow'
import type { Citation } from '../../api/schemas'
import { fmtTimestamp } from '../../lib/format'
import { cn } from '../../lib/utils'
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '../../components/ui/collapsible'
import { getSettings } from '../../store/sessionStore'

interface MessageListProps {
  messages: ChatMessage[]
  flowState: FlowState
  analysingMeta: AnalysingMeta | null
  errorMeta: ErrorMeta | null
  elapsedMs: number
  onCitationClick: (citation: Citation) => void
  onCancel: () => void
  onRetry: () => void
}

function ErrorBubble({ error, onRetry }: { error: ErrorMeta; onRetry: () => void }) {
  const chatUrl = getSettings().chatApiUrl
  return (
    <div className="rounded-xl border border-[var(--danger)]/30 bg-[var(--danger)]/5 p-4 space-y-2">
      <div className="flex items-center gap-2 text-[var(--danger)]">
        <AlertCircle size={14} />
        <span className="text-sm font-medium">Error</span>
        {error.code && (
          <Badge variant="danger" className="text-[10px]">{error.code}</Badge>
        )}
      </div>
      <p className="text-sm text-[var(--text)]">{error.message}</p>
      {error.message.includes("Can't reach") && (
        <p className="text-xs text-[var(--muted)]">
          Chat server: <code className="font-mono bg-[var(--surface-2)] px-1 rounded">{chatUrl}</code>.{' '}
          Change in Settings if incorrect.
        </p>
      )}
      <div className="flex items-center gap-2">
        {error.retryable && (
          <Button size="sm" onClick={onRetry}>
            <RefreshCw size={12} />
            Retry
          </Button>
        )}
        {error.detail && (
          <Collapsible>
            <CollapsibleTrigger asChild>
              <button className="text-[11px] text-[var(--muted)] hover:text-[var(--text)] flex items-center gap-1">
                <ChevronDown size={11} />
                Details
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <pre className="mt-1 text-[10px] font-mono text-[var(--muted)] bg-[var(--surface-2)] rounded p-2 overflow-auto max-h-32 whitespace-pre-wrap">
                {error.detail}
              </pre>
            </CollapsibleContent>
          </Collapsible>
        )}
      </div>
    </div>
  )
}

export function MessageList({
  messages,
  flowState,
  analysingMeta,
  errorMeta,
  elapsedMs,
  onCitationClick,
  onCancel,
  onRetry,
}: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth' })
  }, [messages.length, flowState])

  // Announce status to screen readers
  useEffect(() => {
    const el = document.getElementById('live-announcer')
    if (!el) return
    if (flowState === 'answered') el.textContent = 'Analysis complete. Answer ready.'
    if (flowState === 'error') el.textContent = 'An error occurred. See error message.'
    if (flowState === 'analysing')
      el.textContent = analysingMeta?.phase === 'ingesting'
        ? 'Preparing DAQ inventory…'
        : `Analysing condition ${analysingMeta?.conditionId ?? ''}…`
  }, [flowState, analysingMeta])

  const lastMessageId = messages[messages.length - 1]?.id

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4 space-y-6">
      {messages.map((msg) => (
        <div
          key={msg.id}
          className={cn('flex gap-3', msg.role === 'user' ? 'justify-end' : 'justify-start')}
        >
          {msg.role === 'assistant' && (
            <div className="w-7 h-7 rounded-full bg-[var(--accent-dim)] border border-[var(--accent)]/30 flex items-center justify-center shrink-0 mt-0.5">
              <Bot size={13} className="text-[var(--accent)]" />
            </div>
          )}

          <div className={cn('flex flex-col gap-1 max-w-[80%]', msg.role === 'user' ? 'items-end' : 'items-start')}>
            <span className="text-[10px] text-[var(--muted)] font-mono">{fmtTimestamp(msg.timestamp)}</span>

            {msg.role === 'user' ? (
              <div className="bg-[var(--surface-2)] rounded-2xl rounded-tr-md px-4 py-2.5 text-sm">
                {msg.content}
              </div>
            ) : msg.isLoading && (flowState === 'analysing' || flowState === 'resending' || flowState === 'timeout') && analysingMeta ? (
              <AnalysisProgressCard
                meta={analysingMeta}
                state={flowState as 'analysing' | 'resending' | 'timeout'}
                elapsedMs={elapsedMs}
                onCancel={onCancel}
                onRetry={onRetry}
              />
            ) : msg.isLoading && (flowState === 'sending' || flowState === 'resending') && msg.id === lastMessageId ? (
              <div className="flex flex-col gap-2 w-72 rounded-2xl rounded-tl-md border border-[var(--border)] bg-[var(--surface)] px-4 py-3">
                <div className="flex items-center gap-2 text-sm text-[var(--text)]">
                  <Loader2 size={14} className="text-[var(--accent)] animate-spin" />
                  Waiting for the answer…
                  <span className="ml-auto font-mono text-[11px] text-[var(--muted)]">{Math.floor(elapsedMs / 1000)} s</span>
                </div>
                <p className="text-[11px] text-[var(--muted)]">
                  The language model usually answers in 10–30 s.
                </p>
                <Button variant="ghost" size="sm" onClick={onCancel} className="self-start text-[var(--muted)]">
                  Cancel
                </Button>
              </div>
            ) : msg.isLoading ? (
              // Placeholder restored from an earlier session whose request never finished
              <div className="rounded-2xl rounded-tl-md border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-sm text-[var(--muted)]">
                No answer — this request was interrupted (e.g. the page was reloaded). Ask again.
              </div>
            ) : msg.error ? (
              <ErrorBubble error={msg.error as ErrorMeta} onRetry={onRetry} />
            ) : msg.citations?.length || msg.sources?.length ? (
              <div className="bg-[var(--surface)] rounded-2xl rounded-tl-md border border-[var(--border)] px-4 py-3 max-w-[600px]">
                <AnswerRenderer
                  answer={msg.content}
                  citations={msg.citations ?? []}
                  sources={msg.sources ?? []}
                  findingCount={msg.findingCount ?? msg.citations?.length ?? 0}
                  onCitationClick={onCitationClick}
                />
              </div>
            ) : (
              <div className="bg-[var(--surface)] rounded-2xl rounded-tl-md border border-[var(--border)] px-4 py-3 text-sm">
                {msg.content || '—'}
              </div>
            )}
          </div>

          {msg.role === 'user' && (
            <div className="w-7 h-7 rounded-full bg-[var(--surface-2)] border border-[var(--border)] flex items-center justify-center shrink-0 mt-0.5">
              <User size={13} className="text-[var(--muted)]" />
            </div>
          )}
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  )
}
