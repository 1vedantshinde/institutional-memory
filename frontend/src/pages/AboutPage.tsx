import { Info } from 'lucide-react'

const PIPELINE_STAGES = [
  { id: 1, label: 'DAQ Dataset', sub: '822 CSV recordings · 41 GB · 25 conditions', color: 'var(--muted)' },
  { id: 2, label: 'Ingestion & Quality Gate', sub: 'Validates 7-channel format. Quarantines on first failure. No coercion.', color: 'var(--warn)' },
  { id: 3, label: 'Signal Processing & Analytics', sub: 'Windowed FFT · Mahalanobis distance · Per-condition baselines · Deterministic Python', color: 'var(--accent)' },
  { id: 4, label: 'Metadata Index & Provenance Graph', sub: 'Condition → Recording → SignalWindow → Finding — every result is traceable', color: 'var(--ch-vib-spindle)' },
  { id: 5, label: 'Evidence-Only LLM Orchestrator', sub: 'Reads computed findings. Generates grounded explanations with [Finding N] markers. Never computes.', color: 'var(--ch-current)' },
  { id: 6, label: 'API / Chat Interface', sub: 'POST /chat · Structured citations · Deterministic source links', color: 'var(--ok)' },
]

const RULES = [
  {
    title: 'Deterministic analytics',
    body: 'All numbers — Mahalanobis distances, sample ranges, window IDs, time boundaries — are computed by deterministic Python analytics. The language model reads findings; it does not compute them.',
    color: 'var(--accent)',
  },
  {
    title: 'Traceable provenance',
    body: 'Every finding is linked to Condition → Recording → SignalWindow → Finding ID. You can inspect the exact CSV row range for any claim. Nothing is inferred from incomplete data.',
    color: 'var(--ch-vib-spindle)',
  },
  {
    title: 'Evidence-only explanations',
    body: 'The LLM may only reference findings already computed and indexed. [Finding N] markers link to structured citations. Uncited claims are impossible in the current architecture.',
    color: 'var(--ch-current)',
  },
]

export function AboutPage() {
  return (
    <div className="flex flex-col h-full overflow-y-auto">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-[var(--border)] shrink-0">
        <Info size={14} className="text-[var(--muted)]" />
        <span className="text-sm font-medium">About</span>
      </div>

      <div className="flex-1 p-4 md:p-6 max-w-3xl mx-auto w-full space-y-8">
        <div>
          <h1 className="text-xl font-semibold tracking-tight mb-1">Zero-hallucination pipeline</h1>
          <p className="text-sm text-[var(--muted)] leading-relaxed">
            Institutional Memory explains anomalies in CNC-machining sensor recordings using deterministic analytics plus an evidence-only language model. The AI explains; it never calculates.
          </p>
        </div>

        {/* Pipeline diagram */}
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-widest text-[var(--muted)] mb-4">Signal processing pipeline</h2>
          <div className="relative flex flex-col gap-0" aria-label="6-stage pipeline diagram" role="img">
            {PIPELINE_STAGES.map((stage, i) => (
              <div key={stage.id} className="flex items-stretch gap-4">
                {/* Connector line */}
                <div className="flex flex-col items-center w-8 shrink-0">
                  <div
                    className="w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-[10px] font-mono font-bold border-2"
                    style={{ borderColor: stage.color, color: stage.color, backgroundColor: `color-mix(in srgb, ${stage.color} 12%, transparent)` }}
                  >
                    {stage.id}
                  </div>
                  {i < PIPELINE_STAGES.length - 1 && (
                    <div className="w-px flex-1 my-1" style={{ backgroundColor: 'var(--border)' }} />
                  )}
                </div>

                {/* Stage content */}
                <div className="flex flex-col pb-4 flex-1 pt-1">
                  <p className="text-sm font-semibold" style={{ color: stage.color }}>{stage.label}</p>
                  <p className="text-[11px] text-[var(--muted)] leading-relaxed mt-0.5">{stage.sub}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Rule cards */}
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-widest text-[var(--muted)] mb-4">Core principles</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {RULES.map((rule) => (
              <div
                key={rule.title}
                className="rounded-xl border border-[var(--border)] p-4 flex flex-col gap-2"
                style={{ borderLeftColor: rule.color, borderLeftWidth: 3 }}
              >
                <p className="text-sm font-semibold" style={{ color: rule.color }}>{rule.title}</p>
                <p className="text-xs text-[var(--muted)] leading-relaxed">{rule.body}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Domain facts */}
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-widest text-[var(--muted)] mb-4">Domain facts</h2>
          <table className="w-full text-sm" aria-label="Domain facts">
            <tbody>
              {[
                ['Conditions', '25 (each an (S, F, D) setting: spindle speed, feed, depth)'],
                ['Recordings', '822 CSV files, ~41 GB total'],
                ['Channels', 'Time, Vib_Spindle, Vib_Table, X_Load_Cell, Y_Load_Cell, Z_Load_Cell, Current'],
                ['Anomaly model', 'mahalanobis-diagonal-v3'],
                ['Window size', '2,048 samples with 50% overlap'],
                ['Quality gate', 'Files failing validation are quarantined, never coerced'],
              ].map(([label, value]) => (
                <tr key={label} className="border-b border-[var(--border)] last:border-0">
                  <td className="py-2 pr-4 text-xs text-[var(--muted)] w-36 shrink-0">{label}</td>
                  <td className="py-2 text-xs font-mono text-[var(--text)]">{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
