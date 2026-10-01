import { parsePath } from '../../lib/parsePath'
import { ChevronRight } from 'lucide-react'
import { cn } from '../../lib/utils'

interface ProvenanceTrailProps {
  sourcePath: string
  windowId: string
  findingId: string
  className?: string
}

export function ProvenanceTrail({ sourcePath, windowId, findingId, className }: ProvenanceTrailProps) {
  const parsed = parsePath(sourcePath)

  const steps = [
    {
      label: 'Condition',
      value: parsed.conditionId ? parsed.conditionId : sourcePath.split('/').slice(-2, -1)[0] ?? '—',
    },
    {
      label: 'Recording',
      value: parsed.recordingNumber ? `Recording ${parsed.recordingNumber}` : parsed.basename,
    },
    {
      label: 'Window',
      value: windowId,
    },
    {
      label: 'Finding',
      value: findingId.length > 16 ? `${findingId.slice(0, 16)}…` : findingId,
    },
  ]

  return (
    <div className={cn('flex flex-wrap items-center gap-1', className)} aria-label="Provenance trail">
      {steps.map((step, i) => (
        <span key={step.label} className="flex items-center gap-1">
          <span className="flex flex-col">
            <span className="text-[10px] text-[var(--muted)] leading-none mb-0.5">{step.label}</span>
            <span className="text-[11px] font-mono text-[var(--text)] bg-[var(--surface-2)] px-1.5 py-0.5 rounded">
              {step.value}
            </span>
          </span>
          {i < steps.length - 1 && (
            <ChevronRight size={12} className="text-[var(--muted)] mt-3 shrink-0" />
          )}
        </span>
      ))}
    </div>
  )
}
