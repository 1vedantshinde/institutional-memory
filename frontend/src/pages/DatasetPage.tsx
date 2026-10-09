import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Activity, AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, Info, Search } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as ReTooltip, ResponsiveContainer, Cell } from 'recharts'
import type { TooltipValueType } from 'recharts'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Label } from '../components/ui/label'
import { Switch } from '../components/ui/switch'
import { Badge } from '../components/ui/badge'
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/card'
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '../components/ui/collapsible'
import { postIngest, getProfile } from '../api/core'
import { getConditions } from '../api/proposed'
import { normalizeProfile } from '../api/normalize'
import type { NormalizedProfile } from '../api/normalize'
import { getSettings } from '../store/sessionStore'
import { fmtInt, fmtPercent } from '../lib/format'
import { announce } from '../lib/announce'

const REASON_EXPLANATIONS: Record<string, string> = {
  null_bytes_removed: 'Null bytes were sanitized and logged; the file was still processed through the quality gate.',
  no_valid_header_numeric_match: 'The CSV header did not match the expected 7-channel format.',
  unparseable_csv: 'The file could not be parsed as valid CSV.',
}

function explainReason(code: string): string {
  if (code in REASON_EXPLANATIONS) return REASON_EXPLANATIONS[code]
  if (code.startsWith('column_count_mismatch:')) {
    const n = code.split(':')[1]
    return `Found ${n} columns instead of the required 7 (Time + 6 signal channels).`
  }
  return code
}

function KpiCard({ label, value, sub, variant }: { label: string; value: string | number; sub?: string; variant?: 'ok' | 'warn' | 'danger' | 'default' }) {
  const colors = {
    ok: 'text-[var(--ok)]',
    warn: 'text-[var(--warn)]',
    danger: 'text-[var(--danger)]',
    default: 'text-[var(--text)]',
  }
  return (
    <Card className="flex flex-col gap-1">
      <p className="text-[11px] text-[var(--muted)] uppercase tracking-widest">{label}</p>
      <p className={cn('text-3xl font-mono font-semibold tabular-nums', colors[variant ?? 'default'])}>{typeof value === 'number' ? fmtInt(value) : value}</p>
      {sub && <p className="text-xs text-[var(--muted)]">{sub}</p>}
    </Card>
  )
}

function cn(...classes: (string | undefined | false)[]): string {
  return classes.filter(Boolean).join(' ')
}

export function DatasetPage() {
  const queryClient = useQueryClient()
  const settings = getSettings()
  const [folderPath, setFolderPath] = useState(settings.datasetPath)
  const [configPath, setConfigPath] = useState(settings.configPath)
  const [force, setForce] = useState(false)
  const [running, setRunning] = useState(false)
  const [rawOpen, setRawOpen] = useState(false)
  const [condSearch, setCondSearch] = useState('')
  const useMocks = import.meta.env.VITE_USE_MOCKS === 'true'

  const { mutate: runIngest, isPending: ingesting, error: ingestError } = useMutation({
    mutationFn: () => postIngest({ folder_path: folderPath, config_path: configPath, force }),
    onSuccess: () => {
      setRunning(true)
      queryClient.invalidateQueries({ queryKey: ['profile'] })
      queryClient.invalidateQueries({ queryKey: ['conditions'] })
    },
  })

  const { data: rawProfile, error: profileError } = useQuery({
    queryKey: ['profile'],
    queryFn: getProfile,
    enabled: true,
    refetchInterval: (query) => {
      if (!running) return false
      const data = query.state.data
      if (!data) return 3000
      const norm = normalizeProfile(data)
      return norm.status === 'complete' || norm.status === 'failed' ? false : 3000
    },
    refetchIntervalInBackground: false,
  })

  const { data: conditionsData } = useQuery({
    queryKey: ['conditions'],
    queryFn: getConditions,
    enabled: true,
  })

  const profile: NormalizedProfile | null = rawProfile ? normalizeProfile(rawProfile) : null
  const isComplete = profile?.status === 'complete'
  const isFailed = profile?.status === 'failed' || profile?.status === 'error'

  const reasonData = profile
    ? Object.entries(profile.reasons).map(([reason, count]) => ({ reason, count, label: reason.length > 28 ? reason.slice(0, 28) + '…' : reason }))
    : []

  const quarantineRate = profile && profile.canonical && profile.quarantined != null && profile.discovered != null
    ? profile.quarantined / profile.discovered
    : null

  const filteredConditions = (conditionsData ?? []).filter((c) => {
    if (!condSearch.trim()) return true
    const q = condSearch.toLowerCase()
    return (
      c.condition_id.toLowerCase().includes(q) ||
      `condition ${c.condition_id}`.toLowerCase().includes(q) ||
      String(c.S).includes(q) ||
      String(c.F).includes(q) ||
      String(c.D).includes(q)
    )
  })

  useEffect(() => {
    if (!running) return
    if (isComplete) announce('Ingestion complete. Dataset health results are ready.')
    else if (isFailed) announce('Ingestion failed.')
  }, [running, isComplete, isFailed])

  const ingestErrorMsg = ingestError instanceof Error ? ingestError.message : ingestError ? String(ingestError) : null

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-[var(--border)] shrink-0">
        <Activity size={14} className="text-[var(--muted)]" />
        <span className="text-sm font-medium">Dataset Health</span>
        {useMocks && <Badge variant="warn" className="text-[10px]">mock data</Badge>}
      </div>

      <div className="flex-1 p-4 md:p-6 space-y-6 max-w-4xl mx-auto w-full">
        {/* Ingestion form */}
        <Card>
          <CardHeader>
            <CardTitle>Run ingestion</CardTitle>
            <p className="text-xs text-[var(--muted)]">
              Runs a profile-only pass in the background. Cached runs restore instantly.
            </p>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="folder-path">Dataset folder path</Label>
                <Input
                  id="folder-path"
                  value={folderPath}
                  onChange={(e) => setFolderPath(e.target.value)}
                  className="font-mono text-xs"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="config-path-dataset">Config path</Label>
                <Input
                  id="config-path-dataset"
                  value={configPath}
                  onChange={(e) => setConfigPath(e.target.value)}
                  className="font-mono text-xs"
                />
              </div>
            </div>

            <div className="flex items-center gap-3">
              <Switch
                id="force-reingest"
                checked={force}
                onCheckedChange={setForce}
              />
              <Label htmlFor="force-reingest">Force re-ingest (ignore cache)</Label>
            </div>

            {ingestErrorMsg && (
              <div className="text-sm text-[var(--danger)] bg-[var(--danger)]/5 rounded-lg p-3 border border-[var(--danger)]/20">
                {ingestErrorMsg}
              </div>
            )}

            <Button
              onClick={() => runIngest()}
              disabled={ingesting}
              className="self-start"
            >
              <Activity size={14} />
              {ingesting ? 'Submitting…' : 'Run ingestion'}
            </Button>
          </CardContent>
        </Card>

        {/* Status banner */}
        {running && !isComplete && !isFailed && (
          <div className="flex items-center gap-2 px-4 py-3 rounded-lg border border-[var(--accent)]/20 bg-[var(--accent-dim)] text-sm text-[var(--accent)]" role="status" aria-live="polite">
            <div className="w-2 h-2 rounded-full bg-[var(--accent)] animate-pulse" />
            Running profile pass… polling every 3 s
          </div>
        )}

        {isFailed && (
          <div className="flex items-center gap-2 px-4 py-3 rounded-lg border border-[var(--danger)]/20 bg-[var(--danger)]/5 text-sm text-[var(--danger)]">
            <AlertTriangle size={14} />
            Ingestion failed: {profile?.raw?.message as string ?? 'Unknown error'}
          </div>
        )}

        {/* Results */}
        {isComplete && profile && (
          <>
            {/* KPI cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <KpiCard label="Discovered" value={profile.discovered ?? 0} />
              <KpiCard label="Canonical" value={profile.canonical ?? 0} variant="ok" />
              <KpiCard label="Quarantined" value={profile.quarantined ?? 0} variant={profile.quarantined ? 'warn' : 'default'} />
              <KpiCard
                label="Quarantine rate"
                value={quarantineRate != null ? `${(quarantineRate * 100).toFixed(1)}%` : '—'}
                variant={quarantineRate && quarantineRate > 0.05 ? 'warn' : 'default'}
              />
            </div>

            {/* Quarantine callout */}
            <div className="flex gap-3 px-4 py-3 rounded-lg border border-[var(--warn)]/20 bg-[var(--warn)]/5">
              <AlertTriangle size={15} className="text-[var(--warn)] shrink-0 mt-0.5" />
              <p className="text-sm text-[var(--muted)]">
                <span className="font-semibold text-[var(--text)]">Quarantined files are never repaired or coerced</span> into the 7-channel format. Each rejection is logged with its reason.
              </p>
            </div>

            {/* Reason chart */}
            {reasonData.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle>Quarantine reasons</CardTitle>
                </CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={Math.max(120, reasonData.length * 40)}>
                    <BarChart data={reasonData} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }}>
                      <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--border)" />
                      <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11, fill: 'var(--muted)', fontFamily: 'var(--font-mono)' }} />
                      <YAxis type="category" dataKey="label" width={180} tick={{ fontSize: 11, fill: 'var(--muted)', fontFamily: 'var(--font-mono)' }} />
                      <ReTooltip
                        contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }}
                        formatter={(value: TooltipValueType | undefined) => [typeof value === 'number' ? value.toLocaleString() : String(value ?? '—'), 'files']}
                      />
                      <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                        {reasonData.map((_, i) => (
                          <Cell key={i} fill="var(--warn)" opacity={0.7 + (i % 3) * 0.1} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            )}

            {/* Reason table with explanations */}
            {reasonData.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle>Reason details</CardTitle>
                </CardHeader>
                <CardContent>
                  <table className="w-full text-sm" aria-label="Quarantine reasons table">
                    <thead>
                      <tr className="border-b border-[var(--border)]">
                        <th className="text-left py-2 text-xs text-[var(--muted)] font-medium">Reason code</th>
                        <th className="text-right py-2 text-xs text-[var(--muted)] font-medium w-16">Files</th>
                      </tr>
                    </thead>
                    <tbody>
                      {reasonData.map(({ reason, count }) => (
                        <tr key={reason} className="border-b border-[var(--border)] last:border-0">
                          <td className="py-2.5 pr-4">
                            <p className="font-mono text-xs text-[var(--text)]">{reason}</p>
                            <p className="text-[11px] text-[var(--muted)] mt-0.5">{explainReason(reason)}</p>
                          </td>
                          <td className="py-2.5 text-right font-mono text-sm">{count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardContent>
              </Card>
            )}

            {/* 25 Process Conditions Breakdown */}
            {conditionsData && conditionsData.length > 0 && (
              <Card>
                <CardHeader className="flex flex-row items-center justify-between pb-2">
                  <div>
                    <CardTitle>Process Conditions ({conditionsData.length})</CardTitle>
                    <p className="text-xs text-[var(--muted)] mt-1">
                      Orthogonal Latin Square (S, F, D) machining parameters across all 25 experimental settings.
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="relative">
                      <Search size={12} className="absolute left-2.5 top-2.5 text-[var(--muted)]" />
                      <Input
                        value={condSearch}
                        onChange={(e) => setCondSearch(e.target.value)}
                        placeholder="Search conditions..."
                        className="pl-7 h-8 text-xs w-44 font-mono"
                      />
                    </div>
                    <Badge variant="ok" className="text-[10px]">{conditionsData.length} active</Badge>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="overflow-x-auto max-h-96">
                    <table className="w-full text-sm" aria-label="Process Conditions Table">
                      <thead className="sticky top-0 bg-[var(--surface)] z-10">
                        <tr className="border-b border-[var(--border)] text-xs text-[var(--muted)]">
                          <th className="text-left py-2 px-3 font-medium">Condition ID</th>
                          <th className="text-right py-2 px-3 font-medium">Spindle Speed (S)</th>
                          <th className="text-right py-2 px-3 font-medium">Feed Rate (F)</th>
                          <th className="text-right py-2 px-3 font-medium">Depth of Cut (D)</th>
                          <th className="text-right py-2 px-3 font-medium">Recordings</th>
                          <th className="text-right py-2 px-3 font-medium">Canonical</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredConditions.map((c) => (
                          <tr key={c.condition_id} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--surface-2)] transition-colors">
                            <td className="py-2.5 px-3 font-mono font-medium text-[var(--accent)]">Condition {c.condition_id}</td>
                            <td className="py-2.5 px-3 text-right font-mono text-xs">{c.S} rpm</td>
                            <td className="py-2.5 px-3 text-right font-mono text-xs">{c.F} mm/min</td>
                            <td className="py-2.5 px-3 text-right font-mono text-xs">{c.D.toFixed(2)} mm</td>
                            <td className="py-2.5 px-3 text-right font-mono text-xs text-[var(--muted)]">{c.recording_count}</td>
                            <td className="py-2.5 px-3 text-right font-mono text-xs text-[var(--ok)] font-medium">{c.canonical_count}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            )}
          </>
        )}

        {/* Raw response */}
        {rawProfile && (
          <Collapsible open={rawOpen} onOpenChange={setRawOpen}>
            <CollapsibleTrigger className="flex items-center gap-1.5 text-[11px] text-[var(--muted)] hover:text-[var(--text)] transition-colors">
              {rawOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              Raw API response (GET /profile)
            </CollapsibleTrigger>
            <CollapsibleContent>
              <pre className="mt-2 text-[10px] font-mono text-[var(--muted)] bg-[var(--surface-2)] rounded-lg p-3 overflow-auto max-h-64 whitespace-pre-wrap">
                {JSON.stringify(rawProfile, null, 2)}
              </pre>
            </CollapsibleContent>
          </Collapsible>
        )}
      </div>
    </div>
  )
}
