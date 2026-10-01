import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { screen, fireEvent, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/mocks/server'
import { MOCK_CONFIG } from '@/mocks/fixtures'
import { renderPage, advanceUntil } from '@/test/utils'
import { ConfigPage } from './ConfigPage'

const CORE = 'http://localhost:8001'

beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
afterEach(() => { vi.useRealTimers() })

async function openEditor() {
  renderPage(<ConfigPage />)
  await advanceUntil(() => expect(screen.getByRole('button', { name: /edit/i })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: /edit/i }))
  return screen.getByLabelText(/config json editor/i) as HTMLTextAreaElement
}

function edit(textarea: HTMLTextAreaElement, value: unknown) {
  fireEvent.change(textarea, { target: { value: typeof value === 'string' ? value : JSON.stringify(value, null, 2) } })
}

describe('ConfigPage — edit → confirm → PUT', () => {
  it('shows a per-key diff and only PUTs after confirmation', async () => {
    let putBody: unknown
    server.use(
      http.put(`${CORE}/config`, async ({ request }) => {
        putBody = await request.json()
        return HttpResponse.json({ status: 'ok' })
      }),
    )
    const textarea = await openEditor()
    const { dataset_path: _removed, ...rest } = MOCK_CONFIG
    const edited = { ...rest, config_path: 'config/other.yaml', new_key: 1 }
    edit(textarea, edited)

    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/hot-reload/i)).toBeInTheDocument()
    expect(within(dialog).getByText(/parsing and analysis/i)).toBeInTheDocument()
    expect(within(dialog).getByText('config_path')).toBeInTheDocument()
    expect(within(dialog).getByText('new_key')).toBeInTheDocument()
    expect(within(dialog).getByText('dataset_path')).toBeInTheDocument()
    expect(within(dialog).getByText(/added/i)).toBeInTheDocument()
    expect(within(dialog).getByText(/removed/i)).toBeInTheDocument()
    expect(putBody).toBeUndefined() // nothing sent before confirming

    fireEvent.click(within(dialog).getByRole('button', { name: /confirm update/i }))
    await advanceUntil(() => expect(putBody).toEqual(edited))
    await advanceUntil(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('cancelling the dialog sends nothing', async () => {
    let putCalled = false
    server.use(http.put(`${CORE}/config`, () => { putCalled = true; return HttpResponse.json({}) }))
    const textarea = await openEditor()
    edit(textarea, { ...MOCK_CONFIG, config_path: 'x' })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: /cancel/i }))
    await vi.advanceTimersByTimeAsync(1000)
    expect(putCalled).toBe(false)
  })

  it.each([
    ['malformed JSON', '{ "a": '],
    ['a JSON array', '[1, 2]'],
    ['a JSON number', '42'],
  ])('rejects %s before any dialog or PUT', async (_label, text) => {
    const textarea = await openEditor()
    edit(textarea, text)
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    expect(screen.getByText(/must be a json object|invalid json/i)).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('does not offer to PUT an unchanged config', async () => {
    await openEditor()
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/no changes/i)).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: /confirm update/i })).toBeDisabled()
  })

  it('shows the server error inline when PUT fails', async () => {
    server.use(http.put(`${CORE}/config`, () => HttpResponse.json({ detail: 'unknown key: foo' }, { status: 422 })))
    const textarea = await openEditor()
    edit(textarea, { ...MOCK_CONFIG, foo: 1 })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: /confirm update/i }))
    await advanceUntil(() => expect(screen.getByText(/unknown key: foo/i)).toBeInTheDocument())
  })
})
