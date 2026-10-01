import { useState, useRef, useCallback } from 'react'
import { Send, ChevronDown, ChevronUp } from 'lucide-react'
import { Textarea } from '../../components/ui/textarea'
import { Button } from '../../components/ui/button'
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../../components/ui/select'
import { Input } from '../../components/ui/input'
import { Label } from '../../components/ui/label'
import { CHANNELS, CHANNEL_LABELS, friendlyChannel } from '../../lib/channels'
import { cn } from '../../lib/utils'

interface ComposerProps {
  onSend: (question: string) => void
  onScopedQuery?: (question: string, conditionId: string, channel: string, topK: number) => void
  disabled?: boolean
  prefill?: string
}

const SIGNAL_CHIPS: { id: string; label: string; insert: string }[] = [
  { id: 'Vib_Spindle', label: 'Spindle vib.', insert: 'spindle vibration' },
  { id: 'Vib_Table', label: 'Table vib.', insert: 'table vibration' },
  { id: 'X_Load_Cell', label: 'X load', insert: 'X load cell' },
  { id: 'Y_Load_Cell', label: 'Y load', insert: 'Y load cell' },
  { id: 'Z_Load_Cell', label: 'Z load', insert: 'Z load cell' },
  { id: 'Current', label: 'Motor current', insert: 'motor current' },
]

export function Composer({ onSend, onScopedQuery, disabled, prefill }: ComposerProps) {
  const [value, setValue] = useState(prefill ?? '')
  const [advanced, setAdvanced] = useState(false)
  const [conditionId, setConditionId] = useState('')
  const [channel, setChannel] = useState('')
  const [topK, setTopK] = useState('3')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleSend = useCallback(() => {
    const q = value.trim()
    if (!q || disabled) return

    if (advanced && onScopedQuery && conditionId) {
      onScopedQuery(q, conditionId, channel, parseInt(topK, 10) || 3)
    } else {
      onSend(q)
    }
    setValue('')
  }, [value, disabled, advanced, onScopedQuery, conditionId, channel, topK, onSend])

  const insertChip = (insert: string) => {
    const cur = value
    const next = cur ? `${cur} ${insert}` : insert
    setValue(next)
    textareaRef.current?.focus()
  }

  return (
    <div className="flex flex-col gap-2">
      {/* Signal chips */}
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Quick-insert signal chips">
        {SIGNAL_CHIPS.map((chip) => (
          <button
            key={chip.id}
            type="button"
            onClick={() => insertChip(chip.insert)}
            className="inline-flex items-center px-2 py-1 rounded-full text-[10px] font-mono border border-[var(--border)] text-[var(--muted)] hover:text-[var(--text)] hover:border-[var(--accent)]/50 hover:bg-[var(--accent-dim)] transition-colors disabled:opacity-40"
            aria-label={`Insert "${chip.insert}" into question`}
          >
            {chip.label}
          </button>
        ))}
      </div>

      {/* Main input */}
      <div className="flex gap-2 items-end">
        <Textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about a condition and signal, e.g. condition 4, spindle vibration…"
          rows={3}
          className="flex-1 resize-none"
          aria-label="Question input"
          aria-describedby="composer-hint"
        />
        <Button
          onClick={handleSend}
          disabled={disabled || !value.trim()}
          size="icon"
          aria-label={disabled ? 'Send question (waiting for the current answer)' : 'Send question'}
          title={disabled ? 'Waiting for the current answer' : undefined}
          className="shrink-0 h-[72px] w-10 rounded-md"
        >
          <Send size={15} />
        </Button>
      </div>

      <p id="composer-hint" className="text-[11px] text-[var(--muted)]">
        {disabled ? (
          <span className="text-[var(--accent)]">
            Waiting for the current answer — you can type your next question and send it when this one finishes.
          </span>
        ) : (
          <>Enter to send · Shift+Enter for newline · Mention a condition number and signal, e.g. "condition 4, spindle vibration"</>
        )}
      </p>

      {/* Advanced / Scoped query toggle */}
      <div>
        <button
          onClick={() => setAdvanced((v) => !v)}
          className="flex items-center gap-1 text-[11px] text-[var(--muted)] hover:text-[var(--text)] transition-colors"
          aria-expanded={advanced}
          aria-controls="scoped-query-panel"
        >
          {advanced ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          Scoped query (POST /query with explicit filters)
        </button>

        {advanced && (
          <div
            id="scoped-query-panel"
            className="mt-2 p-3 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] flex flex-wrap gap-3"
          >
            <div className="flex flex-col gap-1 min-w-28">
              <Label htmlFor="scope-condition">Condition ID</Label>
              <Input
                id="scope-condition"
                type="number"
                min={1}
                max={25}
                value={conditionId}
                onChange={(e) => setConditionId(e.target.value)}
                placeholder="1–25"
                className="w-24 text-xs font-mono"
              />
            </div>
            <div className="flex flex-col gap-1 min-w-36">
              <Label htmlFor="scope-channel">Channel</Label>
              <Select value={channel} onValueChange={setChannel}>
                <SelectTrigger id="scope-channel" className="w-44 text-xs">
                  <SelectValue placeholder="All channels" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">All channels</SelectItem>
                  {CHANNELS.map((ch) => (
                    <SelectItem key={ch} value={ch}>{CHANNEL_LABELS[ch]}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1 min-w-20">
              <Label htmlFor="scope-topk">Top K</Label>
              <Input
                id="scope-topk"
                type="number"
                min={1}
                max={10}
                value={topK}
                onChange={(e) => setTopK(e.target.value)}
                className="w-20 text-xs font-mono"
              />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
