import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, AlertTriangle } from 'lucide-react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Label } from '../../components/ui/label'
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../../components/ui/select'
import { Badge } from '../../components/ui/badge'
import { Card, CardHeader, CardTitle, CardContent } from '../../components/ui/card'
import { ChannelBadge } from '../../components/ChannelBadge'
import { getFindings, getWindowSignal } from '../../api/proposed'
import { CHANNELS, CHANNEL_LABELS, CHANNEL_HEX } from '../../lib/channels'
import { fmtInt } from '../../lib/format'

export function WaveformsPage() {
  const [conditionId, setConditionId] = useState('4')
  const [channel, setChannel] = useState('Vib_Spindle')
  const [selectedFinding, setSelectedFinding] = useState<string | null>(null)
  const [selectedWindowId, setSelectedWindowId] = useState<string | null>(null)
  const [recordingId, setRecordingId] = useState<string | null>(null)

  const { data: findings, isLoading: findingsLoading } = useQuery({
    queryKey: ['findings', conditionId, channel],
    queryFn: () => getFindings({ condition_id: conditionId, channel, limit: 20 }),
    enabled: !!conditionId && !!channel,
  })

  const { data: waveform, isLoading: waveformLoading } = useQuery({
    queryKey: ['waveform', recordingId, selectedWindowId],
    queryFn: () => getWindowSignal(recordingId!, selectedWindowId!),
    enabled: !!(recordingId && selectedWindowId),
  })

  const waveformData = waveform?.samples.map((v, i) => ({
    i: waveform.sample_start + i,
    value: v,
  })) ?? []

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      {/* Preview banner */}
      <div className="flex items-center gap-2 px-4 py-2 bg-[var(--warn)]/10 border-b border-[var(--warn)]/20 shrink-0">
        <AlertTriangle size={13} className="text-[var(--warn)]" />
        <span className="text-xs text-[var(--warn)] font-medium">
          Preview — backend endpoint not implemented yet
        </span>
        <Badge variant="warn" className="text-[10px]">GET /findings · GET /recordings/:id/windows/:windowId/signal</Badge>
      </div>

      <div className="flex items-center gap-2 px-4 py-3 border-b border-[var(--border)] shrink-0">
        <Activity size={14} className="text-[var(--muted)]" />
        <span className="text-sm font-medium">Waveforms & Findings</span>
        <Badge variant="warn" className="text-[10px]">mock only</Badge>
      </div>

      <div className="flex-1 p-4 md:p-6 max-w-4xl mx-auto w-full space-y-6">
        <Card>
          <CardContent className="flex flex-wrap gap-4 pt-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="w-condition">Condition ID</Label>
              <Input id="w-condition" type="number" min={1} max={25} value={conditionId} onChange={(e) => setConditionId(e.target.value)} className="w-24 font-mono" />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>Channel</Label>
              <Select value={channel} onValueChange={setChannel}>
                <SelectTrigger className="w-44 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CHANNELS.map((ch) => (
                    <SelectItem key={ch} value={ch}>{CHANNEL_LABELS[ch]}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        {findingsLoading && <div className="h-32 shimmer rounded-xl" />}

        {findings && findings.length > 0 && (
          <Card>
            <CardHeader><CardTitle>Anomalous windows</CardTitle></CardHeader>
            <CardContent>
              <div className="space-y-2">
                {findings.map((f) => (
                  <button
                    key={f.finding_id}
                    onClick={() => {
                      setSelectedFinding(f.finding_id)
                      setSelectedWindowId(f.window_id)
                      setRecordingId('12') // mock recording id
                    }}
                    className={[
                      'w-full text-left px-3 py-2 rounded-lg border transition-colors text-sm',
                      selectedFinding === f.finding_id
                        ? 'border-[var(--accent)] bg-[var(--accent-dim)]'
                        : 'border-[var(--border)] hover:bg-[var(--surface-2)]',
                    ].join(' ')}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-xs">{f.window_id}</span>
                      <ChannelBadge channel={f.channel} size="sm" />
                    </div>
                    <div className="text-[11px] text-[var(--muted)] mt-0.5 font-mono">
                      {fmtInt(f.sample_range.sample_start)} → {fmtInt(f.sample_range.sample_end)}
                      {f.score != null && <span className="ml-2">score: {f.score.toFixed(2)}</span>}
                    </div>
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {waveform && (
          <Card>
            <CardHeader>
              <CardTitle>Signal — {waveform.window_id}</CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={waveformData} margin={{ left: 0, right: 8, top: 4, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="i" tick={{ fontSize: 10, fill: 'var(--muted)', fontFamily: 'var(--font-mono)' }} />
                  <YAxis tick={{ fontSize: 10, fill: 'var(--muted)', fontFamily: 'var(--font-mono)' }} />
                  <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 11 }} />
                  <Line
                    type="monotone"
                    dataKey="value"
                    stroke={CHANNEL_HEX[channel as keyof typeof CHANNEL_HEX] ?? '#60a5fa'}
                    dot={false}
                    strokeWidth={1.5}
                  />
                </LineChart>
              </ResponsiveContainer>
              <p className="text-[11px] text-[var(--muted)] mt-2 font-mono">
                Samples {fmtInt(waveform.sample_start)}–{fmtInt(waveform.sample_start + waveform.samples.length - 1)}
                {waveform.sample_rate && ` · ${fmtInt(waveform.sample_rate)} Hz`}
              </p>
            </CardContent>
          </Card>
        )}

        {waveformLoading && <div className="h-48 shimmer rounded-xl" />}
      </div>
    </div>
  )
}
