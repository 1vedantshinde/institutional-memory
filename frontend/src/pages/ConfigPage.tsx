import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Sliders, Edit2, Save, X, AlertTriangle } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Badge } from '../components/ui/badge'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../components/ui/dialog'
import { getConfig, putConfig } from '../api/core'
import { announce } from '../lib/announce'

type KeyChange = { key: string; kind: 'added' | 'removed' | 'changed' }

function diffKeys(original: Record<string, unknown>, edited: Record<string, unknown>): KeyChange[] {
  const changes: KeyChange[] = []
  const allKeys = new Set([...Object.keys(original), ...Object.keys(edited)])
  for (const key of allKeys) {
    if (!(key in original)) changes.push({ key, kind: 'added' })
    else if (!(key in edited)) changes.push({ key, kind: 'removed' })
    else if (JSON.stringify(original[key]) !== JSON.stringify(edited[key])) changes.push({ key, kind: 'changed' })
  }
  return changes
}

/** Parses the editor text; the config must be a JSON object, not an array or scalar. */
function parseConfig(text: string): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch (e) {
    return { ok: false, error: `Invalid JSON — ${e instanceof Error ? e.message : 'syntax error'}. Fix it before saving.` }
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return { ok: false, error: 'Config must be a JSON object ({ … }) of top-level keys.' }
  }
  return { ok: true, value: parsed as Record<string, unknown> }
}

const CHANGE_VARIANT = { added: 'ok', removed: 'danger', changed: 'warn' } as const

export function ConfigPage() {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState('')
  const [parseError, setParseError] = useState<string | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [changes, setChanges] = useState<KeyChange[]>([])

  const { data: config, isLoading, error } = useQuery({
    queryKey: ['config'],
    queryFn: getConfig,
  })

  const { mutate: saveConfig, isPending: saving, error: saveError } = useMutation({
    mutationFn: (data: Record<string, unknown>) => putConfig(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config'] })
      setEditing(false)
      setConfirmOpen(false)
      announce('Config saved and hot-reloaded.')
    },
  })

  const handleEdit = () => {
    setEditText(JSON.stringify(config, null, 2))
    setParseError(null)
    setEditing(true)
  }

  const handleSaveAttempt = () => {
    const result = parseConfig(editText)
    if (!result.ok) {
      setParseError(result.error)
      return
    }
    setChanges(diffKeys((config ?? {}) as Record<string, unknown>, result.value))
    setParseError(null)
    setConfirmOpen(true)
  }

  const handleConfirmSave = () => {
    const result = parseConfig(editText)
    if (result.ok) saveConfig(result.value)
  }

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)] shrink-0">
        <div className="flex items-center gap-2">
          <Sliders size={14} className="text-[var(--muted)]" />
          <span className="text-sm font-medium">Config</span>
        </div>
        <div className="flex items-center gap-2">
          {editing ? (
            <>
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                <X size={13} /> Cancel
              </Button>
              <Button size="sm" onClick={handleSaveAttempt} disabled={saving}>
                <Save size={13} /> Save
              </Button>
            </>
          ) : (
            <Button size="sm" variant="outline" onClick={handleEdit} disabled={isLoading || !config}>
              <Edit2 size={13} /> Edit
            </Button>
          )}
        </div>
      </div>

      <div className="flex-1 p-4 md:p-6 max-w-3xl mx-auto w-full space-y-4">
        {isLoading && (
          <div className="h-64 rounded-xl bg-[var(--surface-2)] shimmer" />
        )}

        {error && (
          <div className="flex items-center gap-2 p-4 rounded-lg border border-[var(--danger)]/20 bg-[var(--danger)]/5 text-sm text-[var(--danger)]">
            <AlertTriangle size={14} />
            Failed to load config: {error instanceof Error ? error.message : 'Unknown error'}
          </div>
        )}

        {config && !editing && (
          <div className="rounded-xl border border-[var(--border)] overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2 bg-[var(--surface-2)] border-b border-[var(--border)]">
              <span className="text-[11px] font-mono text-[var(--muted)]">GET /config</span>
              <Badge variant="ok" className="text-[10px]">live</Badge>
            </div>
            <pre className="p-4 text-[12px] font-mono text-[var(--text)] overflow-auto max-h-[calc(100vh-200px)] leading-relaxed whitespace-pre-wrap">
              {JSON.stringify(config, null, 2)}
            </pre>
          </div>
        )}

        {editing && (
          <div className="flex flex-col gap-2">
            {parseError && (
              <div role="alert" className="flex items-center gap-2 px-3 py-2 rounded-lg border border-[var(--danger)]/20 bg-[var(--danger)]/5 text-xs text-[var(--danger)]">
                <AlertTriangle size={12} /> {parseError}
              </div>
            )}
            <textarea
              value={editText}
              onChange={(e) => { setEditText(e.target.value); setParseError(null) }}
              className="w-full h-[calc(100vh-280px)] rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 text-[12px] font-mono text-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] resize-none"
              spellCheck={false}
              aria-label="Config JSON editor"
            />
          </div>
        )}

        {saveError && (
          <div role="alert" className="flex items-center gap-2 p-3 rounded-lg border border-[var(--danger)]/20 bg-[var(--danger)]/5 text-sm text-[var(--danger)]">
            <AlertTriangle size={13} />
            Save failed: {saveError instanceof Error ? saveError.message : 'Unknown error'}
          </div>
        )}
      </div>

      {/* Confirmation dialog */}
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm config update</DialogTitle>
            <DialogDescription>
              This will PUT the new config and hot-reload it without a backend restart. It takes effect
              immediately and changes how recordings are parsed and analysed (parsing and analysis).
            </DialogDescription>
          </DialogHeader>
          {changes.length > 0 ? (
            <div className="rounded-lg bg-[var(--surface-2)] p-3">
              <p className="text-[11px] text-[var(--muted)] mb-2">
                {changes.length} top-level {changes.length === 1 ? 'key' : 'keys'} will change:
              </p>
              <ul className="flex flex-col gap-1">
                {changes.map(({ key, kind }) => (
                  <li key={key} className="flex items-center gap-2">
                    <Badge variant={CHANGE_VARIANT[kind]} className="text-[10px] w-16 justify-center">{kind}</Badge>
                    <code className="text-xs font-mono text-[var(--text)] break-all">{key}</code>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="rounded-lg bg-[var(--surface-2)] p-3 text-xs text-[var(--muted)]">
              No changes — the edited config is identical to the active one.
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>Cancel</Button>
            <Button onClick={handleConfirmSave} disabled={saving || changes.length === 0}>
              {saving ? 'Saving…' : 'Confirm update'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
