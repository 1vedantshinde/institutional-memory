import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { MessageSquare, Trash2, Download, Cpu } from 'lucide-react'
import { useChatFlow } from '../features/ask/useChatFlow'
import { Composer } from '../features/ask/Composer'
import { MessageList } from '../features/ask/MessageList'
import { EvidencePanel } from '../features/ask/EvidencePanel'
import { Button } from '../components/ui/button'
import { getMessages, clearMessages, subscribe } from '../store/sessionStore'
import { postQuery } from '../api/core'
import { addMessage, updateMessage, addEvidence } from '../store/sessionStore'
import { parsePath } from '../lib/parsePath'
import type { Citation } from '../api/schemas'
import { fmtTimestamp } from '../lib/format'

const EXAMPLE_PROMPTS = [
  "What changed in spindle vibration for condition 4?",
  "Which windows look abnormal in the X load cell for condition 7?",
  "Explain motor current anomalies for condition 12",
  "Any table vibration issues for condition 2?",
]

function exportMarkdown(messages: ReturnType<typeof getMessages>): void {
  const lines: string[] = ['# DAQ Condition Intelligence — Conversation Export', '']
  for (const msg of messages) {
    if (msg.isLoading) continue // skip in-flight placeholders
    const ts = fmtTimestamp(msg.timestamp)
    if (msg.role === 'user') {
      lines.push(`## [${ts}] Operator`, '', msg.content, '')
    } else if (msg.citations?.length) {
      lines.push(`## [${ts}] System`, '', msg.content, '')
      lines.push('### Citations')
      for (const c of msg.citations) {
        lines.push(`- **${c.label}** (${c.finding_id}): ${c.channel} · ${c.window_id} · ${c.source_path}`)
      }
      lines.push('')
    } else {
      lines.push(`## [${ts}] System`, '', msg.content, '')
    }
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `daq-conversation-${Date.now()}.md`
  a.click()
  URL.revokeObjectURL(url)
}

export function AskPage() {
  const [messages, setMessages] = useState(getMessages)
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null)
  const [evidencePanelOpen, setEvidencePanelOpen] = useState(false)
  const [prefill, setPrefill] = useState('')
  const navigate = useNavigate()

  const { state, analysing, error, elapsedMs, send, cancel, retry } = useChatFlow()

  useEffect(() => {
    return subscribe(() => setMessages(getMessages()))
  }, [])

  const handleCitationClick = useCallback((c: Citation) => {
    setSelectedCitation(c)
    setEvidencePanelOpen(true)
  }, [])

  const handleScopedQuery = useCallback(
    async (question: string, conditionId: string, channel: string, topK: number) => {
      addMessage({ role: 'user', content: `[Scoped] ${question}`, timestamp: new Date() })
      const msgId = addMessage({ role: 'assistant', content: '', timestamp: new Date(), isLoading: true })
      try {
        const res = await postQuery({ question, filters: { condition_id: conditionId, channel: channel || undefined }, top_k: topK })
        updateMessage(msgId, { content: res.answer, citations: res.citations, findingCount: res.finding_count, isLoading: false })
        addEvidence(res.citations.map((c) => ({ citation: c, conditionId: parsePath(c.source_path).conditionId, recordingNumber: parsePath(c.source_path).recordingNumber, firstSeenAt: new Date(), messageId: msgId })))
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'Query failed'
        updateMessage(msgId, { isLoading: false, error: { code: null, message: msg, detail: null } })
      }
    },
    [],
  )

  const handleNewChat = () => {
    clearMessages()
    setSelectedCitation(null)
    setEvidencePanelOpen(false)
  }

  const handleAskAboutWindow = (question: string) => {
    setEvidencePanelOpen(false)
    setPrefill(question)
    setTimeout(() => setPrefill(''), 100)
    send(question)
  }

  const isEmpty = messages.length === 0

  return (
    <div className="flex flex-1 overflow-hidden h-full">
      {/* Main chat column */}
      <div className="flex flex-col flex-1 overflow-hidden">
        {/* Toolbar */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--border)] shrink-0">
          <div className="flex items-center gap-2">
            <MessageSquare size={14} className="text-[var(--muted)]" />
            <span className="text-sm font-medium">Ask</span>
          </div>
          <div className="flex items-center gap-1">
            {messages.length > 0 && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => exportMarkdown(messages)}
                aria-label="Export conversation as Markdown"
              >
                <Download size={13} />
                <span className="hidden sm:inline">Export</span>
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={handleNewChat} aria-label="Start new chat">
              <Trash2 size={13} />
              <span className="hidden sm:inline">New chat</span>
            </Button>
          </div>
        </div>

        {/* Message area */}
        {isEmpty ? (
          <div className="flex-1 flex flex-col items-center justify-center px-4 py-12 gap-6">
            <div className="flex flex-col items-center gap-3 text-center max-w-md">
              <div className="w-12 h-12 rounded-2xl bg-[var(--accent-dim)] border border-[var(--accent)]/20 flex items-center justify-center">
                <Cpu size={20} className="text-[var(--accent)]" />
              </div>
              <h1 className="text-xl font-semibold tracking-tight">Ask about your machine's behavior</h1>
              <p className="text-sm text-[var(--muted)] leading-relaxed">
                Answers are grounded only in computed findings from deterministic analytics. The AI explains — it never calculates.
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-lg">
              {EXAMPLE_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => send(prompt)}
                  className="text-left px-3 py-2.5 rounded-lg border border-[var(--border)] bg-[var(--surface)] hover:bg-[var(--surface-2)] hover:border-[var(--accent)]/30 text-sm text-[var(--muted)] hover:text-[var(--text)] transition-colors"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <MessageList
            messages={messages}
            flowState={state}
            analysingMeta={analysing}
            errorMeta={error}
            elapsedMs={elapsedMs}
            onCitationClick={handleCitationClick}
            onCancel={cancel}
            onRetry={retry}
          />
        )}

        {/* Composer */}
        <div className="border-t border-[var(--border)] p-4 shrink-0 bg-[var(--bg)]">
          <Composer
            onSend={send}
            onScopedQuery={handleScopedQuery}
            disabled={state === 'sending' || state === 'analysing' || state === 'resending'}
            prefill={prefill}
          />
        </div>
      </div>

      {/* Evidence panel — desktop side panel */}
      {evidencePanelOpen && selectedCitation && (
        <div className="hidden md:flex">
          <EvidencePanel
            citation={selectedCitation}
            onClose={() => setEvidencePanelOpen(false)}
            onAskAbout={handleAskAboutWindow}
          />
        </div>
      )}

      {/* Evidence panel — mobile bottom sheet */}
      {evidencePanelOpen && selectedCitation && (
        <div className="md:hidden fixed inset-0 z-50 flex flex-col justify-end">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setEvidencePanelOpen(false)}
            aria-hidden="true"
          />
          <EvidencePanel
            citation={selectedCitation}
            onClose={() => setEvidencePanelOpen(false)}
            onAskAbout={handleAskAboutWindow}
            asSheet
            className="relative z-10"
          />
        </div>
      )}
    </div>
  )
}
