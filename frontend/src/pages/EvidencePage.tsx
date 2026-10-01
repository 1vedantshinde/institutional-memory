import { useState, useEffect } from 'react'
import { BookOpen, Download, ChevronDown, ChevronUp } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Badge } from '../components/ui/badge'
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../components/ui/select'
import { ChannelBadge } from '../components/ChannelBadge'
import { EvidencePanel } from '../features/ask/EvidencePanel'
import { getEvidence, subscribe } from '../store/sessionStore'
import type { SessionEvidence } from '../store/sessionStore'
import type { Citation } from '../api/schemas'
import { CHANNELS, CHANNEL_LABELS } from '../lib/channels'
import { fmtInt, fmtTimestamp } from '../lib/format'
import { useNavigate } from 'react-router-dom'

function exportCsv(entries: SessionEvidence[]) {
  const header = 'label,finding_id,model_version,source_path,channel,window_id,sample_start,sample_end,time_start,time_end,first_seen\n'
  const rows = entries.map((e) => {
    const c = e.citation
    return [
      c.label, c.finding_id, c.model_version, c.source_path, c.channel, c.window_id,
      c.sample_range.sample_start, c.sample_range.sample_end,
      c.time_range?.time_start ?? '', c.time_range?.time_end ?? '',
      e.firstSeenAt.toISOString(),
    ].map((v) => `"${String(v).replace(/"/g, '""')}"`).join(',')
  })
  const blob = new Blob([header + rows.join('\n')], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `daq-evidence-${Date.now()}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

function exportJson(entries: SessionEvidence[]) {
  const blob = new Blob([JSON.stringify(entries.map((e) => e.citation), null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `daq-evidence-${Date.now()}.json`
  a.click()
  URL.revokeObjectURL(url)
}

export function EvidencePage() {
  const [allEvidence, setAllEvidence] = useState(getEvidence)
  const [search, setSearch] = useState('')
  const [channelFilter, setChannelFilter] = useState('')
  const [conditionFilter, setConditionFilter] = useState('')
  const [selected, setSelected] = useState<Citation | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    return subscribe(() => setAllEvidence(getEvidence()))
  }, [])

  const filtered = allEvidence.filter((e) => {
    const c = e.citation
    if (channelFilter && c.channel !== channelFilter) return false
    if (conditionFilter && e.conditionId !== conditionFilter) return false
    if (search) {
      const q = search.toLowerCase()
      return (
        c.finding_id.toLowerCase().includes(q) ||
        c.window_id.toLowerCase().includes(q) ||
        c.source_path.toLowerCase().includes(q) ||
        c.channel.toLowerCase().includes(q)
      )
    }
    return true
  })

  const uniqueConditions = [...new Set(allEvidence.map((e) => e.conditionId).filter(Boolean))] as string[]

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-[var(--border)] shrink-0">
        <BookOpen size={14} className="text-[var(--muted)]" />
        <span className="text-sm font-medium">Evidence</span>
        {allEvidence.length > 0 && (
          <Badge variant="muted" className="text-[10px]">{allEvidence.length} findings</Badge>
        )}
      </div>

      <div className="flex flex-1 overflow-hidden">
        <div className="flex flex-col flex-1 overflow-hidden">
          {/* Filters */}
          <div className="flex flex-wrap items-center gap-2 px-4 py-2 border-b border-[var(--border)] shrink-0">
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search findings, windows, paths…"
              className="w-56 text-xs"
              aria-label="Search evidence"
            />
            <Select value={channelFilter} onValueChange={setChannelFilter}>
              <SelectTrigger className="w-40 text-xs">
                <SelectValue placeholder="All channels" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">All channels</SelectItem>
                {CHANNELS.map((ch) => (
                  <SelectItem key={ch} value={ch}>{CHANNEL_LABELS[ch]}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={conditionFilter} onValueChange={setConditionFilter}>
              <SelectTrigger className="w-36 text-xs">
                <SelectValue placeholder="All conditions" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">All conditions</SelectItem>
                {uniqueConditions.map((id) => (
                  <SelectItem key={id} value={id}>Condition {id}</SelectItem>
                ))}
              </SelectContent>
            </Select>

            <div className="ml-auto flex gap-1">
              <Button size="sm" variant="outline" onClick={() => exportCsv(filtered)} disabled={filtered.length === 0}>
                <Download size={12} /> CSV
              </Button>
              <Button size="sm" variant="outline" onClick={() => exportJson(filtered)} disabled={filtered.length === 0}>
                <Download size={12} /> JSON
              </Button>
            </div>
          </div>

          {/* Table */}
          {allEvidence.length === 0 ? (
            <div className="flex-1 flex flex-col items-center justify-center gap-3 text-center p-8">
              <BookOpen size={32} className="text-[var(--muted)]" />
              <p className="text-sm font-medium">No evidence collected yet</p>
              <p className="text-xs text-[var(--muted)] max-w-xs">
                Evidence accumulates as you chat on the Ask page. Each citation from an answered question appears here.
              </p>
              <Button size="sm" variant="outline" onClick={() => navigate('/')}>Go to Ask</Button>
            </div>
          ) : (
            <div className="flex-1 overflow-auto">
              <table className="w-full text-xs min-w-[700px]" aria-label="Evidence table">
                <thead className="sticky top-0 bg-[var(--surface)] border-b border-[var(--border)] z-10">
                  <tr>
                    <th className="text-left px-3 py-2 text-[var(--muted)] font-medium">Label</th>
                    <th className="text-left px-3 py-2 text-[var(--muted)] font-medium">Finding ID</th>
                    <th className="text-left px-3 py-2 text-[var(--muted)] font-medium">Condition</th>
                    <th className="text-left px-3 py-2 text-[var(--muted)] font-medium">Recording</th>
                    <th className="text-left px-3 py-2 text-[var(--muted)] font-medium">Channel</th>
                    <th className="text-left px-3 py-2 text-[var(--muted)] font-medium">Window</th>
                    <th className="text-left px-3 py-2 text-[var(--muted)] font-medium">Samples</th>
                    <th className="text-left px-3 py-2 text-[var(--muted)] font-medium">First seen</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((e) => (
                    <tr
                      key={e.citation.finding_id}
                      onClick={() => setSelected(e.citation)}
                      className="border-b border-[var(--border)] hover:bg-[var(--surface-2)] cursor-pointer transition-colors"
                      role="button"
                      tabIndex={0}
                      onKeyDown={(ev) => { if (ev.key === 'Enter' || ev.key === ' ') setSelected(e.citation) }}
                      aria-label={`View citation ${e.citation.label}`}
                    >
                      <td className="px-3 py-2 font-semibold text-[var(--accent)]">{e.citation.label}</td>
                      <td className="px-3 py-2 font-mono text-[var(--muted)]">{e.citation.finding_id.slice(0, 18)}…</td>
                      <td className="px-3 py-2 font-mono">{e.conditionId ? `N_${e.conditionId}` : '—'}</td>
                      <td className="px-3 py-2 font-mono">{e.recordingNumber ? `Rec ${e.recordingNumber}` : '—'}</td>
                      <td className="px-3 py-2"><ChannelBadge channel={e.citation.channel} size="sm" /></td>
                      <td className="px-3 py-2 font-mono">{e.citation.window_id}</td>
                      <td className="px-3 py-2 font-mono">
                        {fmtInt(e.citation.sample_range.sample_start)}–{fmtInt(e.citation.sample_range.sample_end)}
                      </td>
                      <td className="px-3 py-2 font-mono text-[var(--muted)]">{fmtTimestamp(e.firstSeenAt)}</td>
                    </tr>
                  ))}
                  {filtered.length === 0 && (
                    <tr>
                      <td colSpan={8} className="px-3 py-6 text-center text-[var(--muted)]">No results match current filters</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Detail panel */}
        {selected && (
          <div className="hidden md:block">
            <EvidencePanel
              citation={selected}
              onClose={() => setSelected(null)}
              onAskAbout={(q) => { setSelected(null); navigate(`/?prefill=${encodeURIComponent(q)}`) }}
            />
          </div>
        )}
      </div>

      {/* Mobile bottom sheet */}
      {selected && (
        <div className="md:hidden fixed inset-0 z-50 flex flex-col justify-end">
          <div className="absolute inset-0 bg-black/50" onClick={() => setSelected(null)} aria-hidden="true" />
          <div className="relative z-10">
            <EvidencePanel
              citation={selected}
              onClose={() => setSelected(null)}
              onAskAbout={(q) => { setSelected(null); navigate(`/?prefill=${encodeURIComponent(q)}`) }}
              asSheet
            />
          </div>
        </div>
      )}
    </div>
  )
}
