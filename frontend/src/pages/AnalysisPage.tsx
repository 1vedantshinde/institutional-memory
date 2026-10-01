import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { BarChart2, CheckCircle2, XCircle, ChevronDown, ChevronUp, Clock } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Label } from '../components/ui/label'
import { Switch } from '../components/ui/switch'
import { Slider } from '../components/ui/slider'
import { Badge } from '../components/ui/badge'
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/card'
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '../components/ui/collapsible'
import { postAnalyse, getAnalyseStatus } from '../api/core'
import { ApiError } from '../api/client'
import { newId } from '../lib/id'
import { normalizeAnalysisStatus } from '../api/normalize'
import type { NormalizedAnalysisStatus } from '../api/normalize'
import { CHANNELS, CHANNEL_LABELS } from '../lib/channels'
import { fmtDuration } from '../lib/format'

interface RecentRun {
  id: string
  conditionId: string
  channels: string[]
  windowSize: number
  overlap: number
  threshold: number
  startedAt: string
  status: string
}

const STORAGE_KEY = 'daq:recent-analysis-runs'

/** api/main.py answers 409 "DAQ analysis is already running." while a job is in progress */
function isAlreadyRunning(err: unknown): boolean {
  return err instanceof ApiError && err.status === 409 && /already running/i.test(err.message)
}

function loadRecentRuns(): RecentRun[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw).slice(0, 10) : []
  } catch { return [] }
}

function saveRun(run: RecentRun) {
  const runs = [run, ...loadRecentRuns().filter((r) => r.id !== run.id)].slice(0, 10)
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(runs)) } catch {}
}

export function AnalysisPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [conditionId, setConditionId] = useState('')
  const [selectedChannels, setSelectedChannels] = useState<string[]>([])
  const [windowSize] = useState(2048)
  const [overlap, setOverlap] = useState(0.5)
  const [threshold, setThreshold] = useState(3.0)
  const [force, setForce] = useState(false)
  // running = polling /analyse/status; jobVisible = job card shown (stays after completion)
  const [running, setRunning] = useState(false)
  const [jobVisible, setJobVisible] = useState(false)
  const [startTime, setStartTime] = useState<number | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [rawOpen, setRawOpen] = useState(false)
  const [recentRuns, setRecentRuns] = useState<RecentRun[]>(loadRecentRuns)
  const [currentRunId, setCurrentRunId] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    if (!running || !startTime) return
    const id = setInterval(() => setElapsed(Date.now() - startTime), 500)
    return () => clearInterval(id)
  }, [running, startTime])

  // Show and poll a job that is already running on the backend (started before
  // this page was opened, or found via 409 "already running"). Scope details
  // come from the latest recent run when it was started from this browser.
  const attachToRunningJob = () => {
    const last = loadRecentRuns()[0]
    if (last?.status === 'running') {
      setCurrentRunId(last.id)
      setConditionId(last.conditionId)
      setSelectedChannels(last.channels)
      setStartTime(Date.parse(last.startedAt) || Date.now())
    } else {
      setCurrentRunId(null)
      setStartTime(Date.now())
    }
    queryClient.removeQueries({ queryKey: ['analyse-status'] })
    setRunning(true)
    setJobVisible(true)
  }

  // On open: re-attach to a job still running (polling stops when you leave the page)
  useEffect(() => {
    let active = true
    getAnalyseStatus()
      .then((raw) => {
        if (!active) return
        const backendStatus = normalizeAnalysisStatus(raw).status
        if (backendStatus === 'running') {
          setNotice('An analysis started earlier is still running — showing its progress.')
          attachToRunningJob()
        } else if (backendStatus === 'complete') {
          // A run left "running" in this browser finished while the page was closed
          const runs = loadRecentRuns()
          if (runs[0]?.status === 'running') {
            runs[0] = { ...runs[0], status: 'complete' }
            try { localStorage.setItem(STORAGE_KEY, JSON.stringify(runs)) } catch {}
            setRecentRuns(runs)
          }
        }
      })
      .catch(() => { /* no ingest yet, or backend down: nothing to attach to */ })
    return () => { active = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const { mutate: startAnalysis, isPending, error: startError } = useMutation({
    mutationFn: () =>
      postAnalyse({
        condition_id: conditionId,
        channels: selectedChannels.length > 0 ? selectedChannels : undefined,
        window_size_samples: windowSize,
        overlap,
        anomaly_threshold: threshold,
        force,
      }),
    onMutate: () => setNotice(null),
    onError: (err) => {
      if (isAlreadyRunning(err)) {
        setNotice('Another analysis is already running on the backend — showing its progress. Start this one when it finishes.')
        attachToRunningJob()
      }
    },
    onSuccess: () => {
      const runId = newId()
      setCurrentRunId(runId)
      const run: RecentRun = {
        id: runId,
        conditionId,
        channels: selectedChannels,
        windowSize,
        overlap,
        threshold,
        startedAt: new Date().toISOString(),
        status: 'running',
      }
      saveRun(run)
      setRecentRuns(loadRecentRuns())
      // Drop the previous run's cached status so a stale "complete" can't end this run
      queryClient.removeQueries({ queryKey: ['analyse-status'] })
      setRunning(true)
      setJobVisible(true)
      setStartTime(Date.now())
    },
  })

  const { data: rawStatus } = useQuery({
    queryKey: ['analyse-status'],
    queryFn: getAnalyseStatus,
    enabled: running,
    refetchInterval: (query) => {
      if (!running) return false
      const data = query.state.data
      if (!data) return 3000
      const norm = normalizeAnalysisStatus(data)
      return norm.status === 'complete' || norm.status === 'error' || norm.status === 'failed' ? false : 3000
    },
    refetchIntervalInBackground: false,
  })

  const status: NormalizedAnalysisStatus | null = rawStatus ? normalizeAnalysisStatus(rawStatus) : null
  const isComplete = status?.status === 'complete'
  const isError = status?.status === 'error' || status?.status === 'failed'

  useEffect(() => {
    if (!(isComplete || isError)) return
    setRunning(false)
    if (currentRunId) {
      const runs = loadRecentRuns().map((r) =>
        r.id === currentRunId ? { ...r, status: isComplete ? 'complete' : 'error' } : r,
      )
      localStorage.setItem(STORAGE_KEY, JSON.stringify(runs))
      setRecentRuns(runs)
    }
  }, [isComplete, isError, currentRunId])

  // "Already running" is handled by attaching to that job (see onError), not shown as a failure
  const startErrorMsg =
    startError instanceof Error && !isAlreadyRunning(startError) ? startError.message : null

  const toggleChannel = (ch: string) => {
    setSelectedChannels((prev) =>
      prev.includes(ch) ? prev.filter((c) => c !== ch) : [...prev, ch],
    )
  }

  const handleAskAboutScope = () => {
    const chLabel = selectedChannels.length === 1 ? CHANNEL_LABELS[selectedChannels[0] as keyof typeof CHANNEL_LABELS] : 'signals'
    const q = `What changed in ${chLabel} for condition ${conditionId}?`
    navigate(`/?prefill=${encodeURIComponent(q)}`)
  }

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-[var(--border)] shrink-0">
        <BarChart2 size={14} className="text-[var(--muted)]" />
        <span className="text-sm font-medium">Analysis</span>
      </div>

      <div className="flex-1 p-4 md:p-6 max-w-4xl mx-auto w-full space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>Run anomaly analysis</CardTitle>
            <p className="text-xs text-[var(--muted)]">
              Fits per-condition baselines from canonical recordings only. Changing S/F/D is never mistaken for a fault.
            </p>
          </CardHeader>
          <CardContent className="space-y-5">
            {/* Condition ID */}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="condition-id">Condition ID (1–25)</Label>
              <Input
                id="condition-id"
                type="number"
                min={1}
                max={25}
                value={conditionId}
                onChange={(e) => setConditionId(e.target.value)}
                className="w-32 font-mono"
                placeholder="e.g. 4"
              />
            </div>

            {/* Channel selection */}
            <div className="flex flex-col gap-1.5">
              <Label>Channels <span className="text-[var(--muted)]">(empty = all)</span></Label>
              <div className="flex flex-wrap gap-2">
                {CHANNELS.map((ch) => (
                  <button
                    key={ch}
                    type="button"
                    onClick={() => toggleChannel(ch)}
                    className={[
                      'px-3 py-1.5 rounded-full text-xs font-mono border transition-colors',
                      selectedChannels.includes(ch)
                        ? 'border-[var(--accent)] bg-[var(--accent-dim)] text-[var(--accent)]'
                        : 'border-[var(--border)] text-[var(--muted)] hover:text-[var(--text)] hover:border-[var(--accent)]/30',
                    ].join(' ')}
                    aria-pressed={selectedChannels.includes(ch)}
                  >
                    {CHANNEL_LABELS[ch]}
                  </button>
                ))}
              </div>
              {selectedChannels.length === 0 && (
                <p className="text-[11px] text-[var(--muted)]">All channels will be analysed. Select specific channels for faster runs.</p>
              )}
            </div>

            {/* Overlap slider */}
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <Label>Overlap: <span className="font-mono">{overlap.toFixed(2)}</span></Label>
                <span className="text-[11px] text-[var(--muted)] font-mono">Window: {windowSize} samples</span>
              </div>
              <Slider
                min={0}
                max={0.9}
                step={0.05}
                value={[overlap]}
                onValueChange={([v]) => setOverlap(v)}
                aria-label="Overlap"
              />
            </div>

            {/* Threshold */}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="threshold">Anomaly threshold (σ)</Label>
              <Input
                id="threshold"
                type="number"
                min={1}
                max={10}
                step={0.1}
                value={threshold}
                onChange={(e) => setThreshold(parseFloat(e.target.value) || 3.0)}
                className="w-28 font-mono"
              />
            </div>

            {/* Force */}
            <div className="flex items-center gap-3">
              <Switch id="force-analysis" checked={force} onCheckedChange={setForce} />
              <Label htmlFor="force-analysis">Force recompute (ignore cached results)</Label>
            </div>

            {/* Model info */}
            <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-[var(--surface-2)] text-[11px] text-[var(--muted)]">
              <BarChart2 size={12} className="mt-0.5 shrink-0" />
              <span>Model: <code className="font-mono text-[var(--text)]">mahalanobis-diagonal-v3</code> · Per-condition baselines fitted from canonical recordings only.</span>
            </div>

            {startErrorMsg && (
              <div role="alert" className="text-sm text-[var(--danger)] bg-[var(--danger)]/5 rounded-lg p-3 border border-[var(--danger)]/20">
                {startErrorMsg}
                {/ingest/i.test(startErrorMsg) && (
                  <>
                    {' '}
                    <Link to="/dataset" className="underline font-medium">Go to Dataset Health</Link> to run ingestion first.
                  </>
                )}
              </div>
            )}
            {notice && (
              <div role="status" className="text-sm text-[var(--accent)] bg-[var(--accent-dim)] rounded-lg p-3 border border-[var(--accent)]/20">
                {notice}
              </div>
            )}

            <Button
              onClick={() => startAnalysis()}
              disabled={isPending || !conditionId || running}
              className="self-start"
            >
              {isPending || running ? 'Running…' : 'Start analysis'}
            </Button>
          </CardContent>
        </Card>

        {/* Job status card */}
        {jobVisible && (
          <Card className="border-[var(--accent)]/20">
            <CardContent className="pt-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <div
                    className={[
                      'w-2 h-2 rounded-full',
                      isComplete ? 'bg-[var(--ok)]' : isError ? 'bg-[var(--danger)]' : 'bg-[var(--accent)] animate-pulse',
                    ].join(' ')}
                  />
                  <span className="text-sm font-medium" role="status" aria-live="polite">
                    {isComplete ? 'Complete' : isError ? 'Failed' : 'Running'}
                  </span>
                </div>
                <span className="text-[11px] font-mono text-[var(--muted)]">
                  <Clock size={10} className="inline mr-1" />
                  {fmtDuration(elapsed)}
                </span>
              </div>

              {status?.message && (
                <p className="text-sm text-[var(--muted)]">{status.message}</p>
              )}

              <div className="flex flex-wrap gap-2 mt-3">
                <Badge variant="default" className="text-[10px]">condition {conditionId}</Badge>
                {selectedChannels.length > 0
                  ? selectedChannels.map((ch) => <Badge key={ch} variant="muted" className="text-[10px]">{ch}</Badge>)
                  : <Badge variant="muted" className="text-[10px]">all channels</Badge>}
                <Badge variant="accent" className="text-[10px]">{status?.modelVersion ?? 'mahalanobis-diagonal-v3'}</Badge>
                <Badge variant="muted" className="text-[10px]">window {windowSize}</Badge>
                <Badge variant="muted" className="text-[10px]">overlap {overlap}</Badge>
                <Badge variant="muted" className="text-[10px]">threshold {threshold}σ</Badge>
              </div>

              {isComplete && (
                <div className="flex gap-2 mt-4">
                  <Button size="sm" onClick={handleAskAboutScope}>Ask about this scope</Button>
                  <Button size="sm" variant="outline" onClick={() => { setRunning(false); setJobVisible(false); setConditionId(''); setSelectedChannels([]) }}>Run another</Button>
                </div>
              )}

              {isError && (
                <p className="mt-2 text-sm text-[var(--danger)]">{status?.error ?? status?.message ?? 'Analysis failed.'}</p>
              )}
            </CardContent>
          </Card>
        )}

        {/* Raw response */}
        {rawStatus && (
          <Collapsible open={rawOpen} onOpenChange={setRawOpen}>
            <CollapsibleTrigger className="flex items-center gap-1.5 text-[11px] text-[var(--muted)] hover:text-[var(--text)] transition-colors">
              {rawOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              Raw API response (GET /analyse/status)
            </CollapsibleTrigger>
            <CollapsibleContent>
              <pre className="mt-2 text-[10px] font-mono text-[var(--muted)] bg-[var(--surface-2)] rounded-lg p-3 overflow-auto max-h-48 whitespace-pre-wrap">
                {JSON.stringify(rawStatus, null, 2)}
              </pre>
            </CollapsibleContent>
          </Collapsible>
        )}

        {/* Recent runs */}
        {recentRuns.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Recent runs</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {recentRuns.map((run) => (
                  <div key={run.id} className="flex items-center justify-between gap-3 py-2 border-b border-[var(--border)] last:border-0">
                    <div className="flex items-center gap-2 flex-wrap min-w-0">
                      <Badge variant={run.status === 'complete' ? 'ok' : run.status === 'error' ? 'danger' : 'warn'} className="text-[10px] shrink-0">
                        {run.status}
                      </Badge>
                      <span className="font-mono text-xs text-[var(--muted)] shrink-0">N_{run.conditionId}</span>
                      <span className="text-[11px] text-[var(--muted)] truncate">
                        {run.channels.length ? run.channels.join(', ') : 'all channels'}
                      </span>
                    </div>
                    <span className="text-[10px] font-mono text-[var(--muted)] shrink-0">
                      {new Date(run.startedAt).toLocaleTimeString()}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}
