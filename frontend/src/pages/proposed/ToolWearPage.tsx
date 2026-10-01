import { useQuery } from '@tanstack/react-query'
import { BarChart2, AlertTriangle } from 'lucide-react'
import { Badge } from '../../components/ui/badge'
import { Card, CardHeader, CardTitle, CardContent } from '../../components/ui/card'
import { getToolWearEvaluation } from '../../api/proposed'
import { fmtNum } from '../../lib/format'

export function ToolWearPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['tool-wear-eval'],
    queryFn: getToolWearEvaluation,
  })

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      {/* Preview banner */}
      <div className="flex items-center gap-2 px-4 py-2 bg-[var(--warn)]/10 border-b border-[var(--warn)]/20 shrink-0">
        <AlertTriangle size={13} className="text-[var(--warn)]" />
        <span className="text-xs text-[var(--warn)] font-medium">
          Preview — backend endpoint not implemented yet
        </span>
        <Badge variant="warn" className="text-[10px]">GET /tool-wear/evaluation</Badge>
      </div>

      <div className="flex items-center gap-2 px-4 py-3 border-b border-[var(--border)] shrink-0">
        <BarChart2 size={14} className="text-[var(--muted)]" />
        <span className="text-sm font-medium">Tool Wear Prediction</span>
        <Badge variant="warn" className="text-[10px]">mock only</Badge>
      </div>

      <div className="flex-1 p-4 md:p-6 max-w-3xl mx-auto w-full space-y-6">
        <div className="px-4 py-3 rounded-lg border border-[var(--warn)]/20 bg-[var(--warn)]/5 text-sm text-[var(--muted)]">
          Tool-wear prediction is trained offline via a CLI script producing <code className="font-mono bg-[var(--surface-2)] px-1 rounded">model.joblib</code> and <code className="font-mono bg-[var(--surface-2)] px-1 rounded">evaluation.json</code>. This page reads the evaluation results via a proposed <code className="font-mono bg-[var(--surface-2)] px-1 rounded">GET /tool-wear/evaluation</code> endpoint that does not yet exist.
        </div>

        {isLoading && <div className="h-48 shimmer rounded-xl" />}

        {error && (
          <div className="text-sm text-[var(--danger)]">Failed to load: {error instanceof Error ? error.message : 'Unknown error'}</div>
        )}

        {data && (
          <>
            <div className="grid grid-cols-3 gap-4">
              {[
                { label: 'MAE', value: fmtNum(data.mae, 4), sub: 'Mean absolute error' },
                { label: 'RMSE', value: fmtNum(data.rmse, 4), sub: 'Root mean squared error' },
                { label: 'R²', value: fmtNum(data.r2, 4), sub: 'Coefficient of determination', highlight: data.r2 > 0.9 },
              ].map((m) => (
                <Card key={m.label} className="flex flex-col gap-1">
                  <p className="text-[11px] text-[var(--muted)] uppercase tracking-widest">{m.label}</p>
                  <p className={['text-2xl font-mono font-semibold', m.highlight ? 'text-[var(--ok)]' : 'text-[var(--text)]'].join(' ')}>{m.value}</p>
                  <p className="text-[11px] text-[var(--muted)]">{m.sub}</p>
                </Card>
              ))}
            </div>

            <Card>
              <CardHeader><CardTitle>Model metadata</CardTitle></CardHeader>
              <CardContent>
                <table className="w-full text-sm">
                  <tbody>
                    {data.model_path && (
                      <tr className="border-b border-[var(--border)]">
                        <td className="py-2 text-xs text-[var(--muted)] pr-4">Model path</td>
                        <td className="py-2 text-xs font-mono">{data.model_path}</td>
                      </tr>
                    )}
                    {data.evaluated_at && (
                      <tr>
                        <td className="py-2 text-xs text-[var(--muted)] pr-4">Evaluated at</td>
                        <td className="py-2 text-xs font-mono">{data.evaluated_at}</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </div>
  )
}
