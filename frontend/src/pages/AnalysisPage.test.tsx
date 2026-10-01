import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { screen, fireEvent } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/mocks/server'
import { renderPage, advanceUntil } from '@/test/utils'
import { AnalysisPage } from './AnalysisPage'

const CORE = 'http://localhost:8001'

beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
afterEach(() => { vi.useRealTimers() })

function startRun(conditionId: string, channelLabel?: RegExp) {
  fireEvent.change(screen.getByLabelText(/condition id/i), { target: { value: conditionId } })
  if (channelLabel) fireEvent.click(screen.getByRole('button', { name: channelLabel }))
  fireEvent.click(screen.getByRole('button', { name: /start analysis/i }))
}

describe('AnalysisPage — analyse → poll → status', () => {
  it('posts /analyse, polls running → complete, then hands off to Ask with a prefilled question', async () => {
    let analyseBody: Record<string, unknown> | undefined
    let polls = 0
    server.use(
      http.post(`${CORE}/analyse`, async ({ request }) => {
        analyseBody = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ status: 'running' }, { status: 202 })
      }),
      http.get(`${CORE}/analyse/status`, () => {
        if (!analyseBody) return HttpResponse.json({ status: 'idle' })
        return HttpResponse.json(++polls < 3
          ? { status: 'running' }
          : { status: 'complete', model_version: 'mahalanobis-diagonal-v3', message: 'Analysis complete. 12 anomalous windows detected across 2 recordings.' })
      }),
    )

    const { location } = renderPage(<AnalysisPage />)
    startRun('4', /spindle/i)

    await advanceUntil(() => expect(screen.getByText('Running')).toBeInTheDocument())
    expect(analyseBody).toMatchObject({
      condition_id: '4',
      channels: ['Vib_Spindle'],
      window_size_samples: 2048,
      overlap: 0.5,
      anomaly_threshold: 3,
      force: false,
    })

    await advanceUntil(() => expect(screen.getByText('Complete')).toBeInTheDocument())
    expect(screen.getByText(/12 anomalous windows/i)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /ask about this scope/i }))
    const prefill = new URLSearchParams(location.current.split('?')[1]).get('prefill')
    expect(location.current.startsWith('/?')).toBe(true)
    expect(prefill).toMatch(/spindle vibration for condition 4\?$/i)
  })

  it('shows the error state and message when status reports failure', async () => {
    server.use(
      http.get(`${CORE}/analyse/status`, () =>
        HttpResponse.json({ status: 'error', error: 'No canonical recordings for condition 99' }),
      ),
    )
    renderPage(<AnalysisPage />)
    startRun('99')

    await advanceUntil(() => expect(screen.getByText(/no canonical recordings for condition 99/i)).toBeInTheDocument())
    expect(screen.getByText('Failed')).toBeInTheDocument()
  })

  it('a second run polls afresh instead of reusing the previous run’s "complete"', async () => {
    renderPage(<AnalysisPage />)
    startRun('4')
    await advanceUntil(() => expect(screen.getByText('Complete')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /run another/i }))
    startRun('7')

    await advanceUntil(() => expect(screen.getByText('Running')).toBeInTheDocument())
    await advanceUntil(() => expect(screen.getByText('Complete')).toBeInTheDocument())
    expect(screen.getByText('condition 7')).toBeInTheDocument()
  })

  it('shows the backend 409 when nothing has been ingested, with a link to Dataset Health', async () => {
    server.use(
      http.post(`${CORE}/analyse`, () =>
        HttpResponse.json({ detail: 'Run POST /ingest on a DAQ folder first.' }, { status: 409 })),
    )
    renderPage(<AnalysisPage />)
    startRun('4')

    await advanceUntil(() => expect(screen.getByRole('alert')).toHaveTextContent('Run POST /ingest on a DAQ folder first.'))
    expect(screen.getByRole('link', { name: /dataset health/i })).toHaveAttribute('href', '/dataset')
    expect(screen.getByRole('button', { name: /start analysis/i })).toBeEnabled()
  })

  it('re-attaches to a job that is still running when the page is opened', async () => {
    localStorage.setItem('daq:recent-analysis-runs', JSON.stringify([
      { id: 'r1', conditionId: '12', channels: ['Current'], windowSize: 2048, overlap: 0.5, threshold: 3, startedAt: new Date().toISOString(), status: 'running' },
    ]))
    let polls = 0
    server.use(http.get(`${CORE}/analyse/status`, () =>
      HttpResponse.json(++polls < 3 ? { status: 'running' } : { status: 'complete', message: 'done' })))

    renderPage(<AnalysisPage />)

    await advanceUntil(() => expect(screen.getByText(/still running — showing its progress/i)).toBeInTheDocument())
    expect(screen.getByText('condition 12')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /running…/i })).toBeDisabled()
    await advanceUntil(() => expect(screen.getByText('Complete')).toBeInTheDocument())
    expect(JSON.parse(localStorage.getItem('daq:recent-analysis-runs')!)[0].status).toBe('complete')
  })

  it('on 409 "already running", follows the running job instead of failing', async () => {
    let started = false
    server.use(
      http.post(`${CORE}/analyse`, () => {
        started = true
        return HttpResponse.json({ detail: 'DAQ analysis is already running.' }, { status: 409 })
      }),
      http.get(`${CORE}/analyse/status`, () =>
        HttpResponse.json({ status: started ? 'running' : 'idle' })),
    )
    renderPage(<AnalysisPage />)
    startRun('4')

    await advanceUntil(() => expect(screen.getByText(/another analysis is already running/i)).toBeInTheDocument())
    expect(screen.getByText('Running')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
