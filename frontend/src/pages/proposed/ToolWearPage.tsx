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
      <div className="flex items-center gap-2 px-4 py-3 border-b border-[var(--border)] shrink-0">
        <BarChart2 size={14} className="text-[var(--accent)]" />
        <span className="text-sm font-medium">Tool Wear Prediction</span>
        <Badge variant="ok" className="text-[10px]">Live Model Evaluation</Badge>
      </div>

      <div className="flex-1 p-4 md:p-6 max-w-3xl mx-auto w-full space-y-6">
        <div className="px-4 py-3 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] text-sm text-[var(--muted)]">
          Tool-wear regression model evaluation metrics loaded from <code className="font-mono bg-[var(--surface)] px-1 py-0.5 rounded text-[var(--text)]">artifacts/tool_wear/evaluation.json</code>.
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
