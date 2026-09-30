import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { screen, fireEvent } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/mocks/server'
import { renderPage, advanceUntil } from '@/test/utils'
import { DatasetPage } from './DatasetPage'

const CORE = 'http://localhost:8001'

beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
afterEach(() => { vi.useRealTimers() })

describe('DatasetPage — ingest → poll → profile', () => {
  it('posts /ingest, polls /profile through running → complete, and renders KPIs and reasons', async () => {
    let ingestBody: unknown
    let profileCalls = 0
    server.events.on('request:start', ({ request }) => {
      if (request.url === `${CORE}/profile`) profileCalls++
    })
    server.use(
      http.post(`${CORE}/ingest`, async ({ request }) => {
        ingestBody = await request.json()
        return HttpResponse.json({ status: 'accepted' }, { status: 202 })
      }),
    )

    renderPage(<DatasetPage />)
    fireEvent.click(screen.getByRole('switch'))
    fireEvent.click(screen.getByRole('button', { name: /run ingestion/i }))

    await advanceUntil(() => expect(screen.getByText(/running profile pass/i)).toBeInTheDocument())
    expect(ingestBody).toEqual({
      folder_path: 'dataset/Readngs_DAQ_Data',
      config_path: 'config/domain.yaml',
      force: true,
    })

    await advanceUntil(() => expect(screen.getByText('Discovered')).toBeInTheDocument())
    expect(profileCalls).toBeGreaterThanOrEqual(2) // running, then complete
    expect(screen.queryByText(/running profile pass/i)).not.toBeInTheDocument()

    expect(screen.getByText('822')).toBeInTheDocument()
    expect(screen.getByText('815')).toBeInTheDocument()
    expect(screen.getByText('0.9%')).toBeInTheDocument() // 7 / 822
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument()
    expect(screen.getAllByText('column_count_mismatch:4').length).toBeGreaterThan(0)
    expect(screen.getByText(/never repaired or coerced/i)).toBeInTheDocument()

    // Polling stops once complete
    const settled = profileCalls
    await vi.advanceTimersByTimeAsync(10_000)
    expect(profileCalls).toBe(settled)
  })

  it('tolerates an unknown profile shape (nested summary, alternate key names)', async () => {
    server.use(
      http.get(`${CORE}/profile`, () =>
        HttpResponse.json({
          status: 'complete',
          summary: { total: 10, canonical_count: 8, quarantined_count: 2, per_reason: { mystery_code: 2 } },
          extra_field: true,
        }),
      ),
    )
    renderPage(<DatasetPage />)
    fireEvent.click(screen.getByRole('button', { name: /run ingestion/i }))

    await advanceUntil(() => expect(screen.getByText('Discovered')).toBeInTheDocument())
    expect(screen.getByText('10')).toBeInTheDocument()
    expect(screen.getAllByText('mystery_code').length).toBeGreaterThan(0)
    fireEvent.click(screen.getByText(/raw api response/i))
    expect(screen.getByText(/extra_field/)).toBeInTheDocument()
  })

  it('shows the exact path message from a 400', async () => {
    const detail = 'folder_path not found: expected dataset/Readngs_DAQ_Data'
    server.use(http.post(`${CORE}/ingest`, () => HttpResponse.json({ detail }, { status: 400 })))

    renderPage(<DatasetPage />)
    fireEvent.click(screen.getByRole('button', { name: /run ingestion/i }))

    await advanceUntil(() => expect(screen.getByText(detail)).toBeInTheDocument())
  })
})
