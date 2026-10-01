import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useChatFlow } from './useChatFlow'
import * as chatApi from '../../api/chat'
import * as sessionStore from '../../store/sessionStore'

vi.mock('../../api/chat')
vi.mock('../../store/sessionStore', () => ({
  addMessage: vi.fn(() => 'mock-msg-id'),
  updateMessage: vi.fn(),
  addEvidence: vi.fn(),
}))

const mockedPostChat = vi.mocked(chatApi.postChat)
const mockedGetChatStatus = vi.mocked(chatApi.getChatStatus)

beforeEach(() => {
  // shouldAdvanceTime lets Testing Library's waitFor (which only recognises
  // Jest's fake timers) keep polling while we still control poll intervals.
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.clearAllMocks()
})

afterEach(() => {
  vi.useRealTimers()
})

const READY_RESPONSE: chatApi.ChatResponse = {
  type: 'ready',
  status: 200,
  data: {
    answer: 'Test answer [Finding 1].',
    citations: [
      {
        label: 'Finding 1',
        finding_id: 'f-001',
        model_version: 'mahalanobis-diagonal-v3',
        source_path: 'dataset/N_4/Recording 12.csv',
        channel: 'Vib_Spindle',
        window_id: 'win-12-004',
        sample_range: { sample_start: 4096, sample_end: 6144 },
        time_range: { time_start: 0.41, time_end: 0.61 },
      },
    ],
    finding_count: 1,
  },
}

const ANALYSING_RESPONSE: chatApi.ChatResponse = {
  type: 'analysing',
  status: 202,
  data: {
    status: 'analysing',
    condition_id: '4',
    channel: 'Vib_Spindle',
    message: 'Analysing...',
    status_url: '/chat/status',
  },
}

describe('useChatFlow', () => {
  it('starts in idle state', () => {
    const { result } = renderHook(() => useChatFlow())
    expect(result.current.state).toBe('idle')
  })

  it('transitions idle → sending → answered on 200', async () => {
    mockedPostChat.mockResolvedValueOnce(READY_RESPONSE)
    const { result } = renderHook(() => useChatFlow())

    act(() => { result.current.send('What changed in spindle vibration?') })
    expect(result.current.state).toBe('sending')

    await waitFor(() => expect(result.current.state).toBe('answered'))
    expect(sessionStore.addEvidence).toHaveBeenCalledOnce()
  })

  it('transitions idle → sending → analysing → resending → answered on 202→poll→200', async () => {
    mockedPostChat
      .mockResolvedValueOnce(ANALYSING_RESPONSE)
      .mockResolvedValueOnce(READY_RESPONSE)
    mockedGetChatStatus
      .mockResolvedValueOnce({ status: 'analysing' })
      .mockResolvedValueOnce({ status: 'analysing' })
      .mockResolvedValueOnce({ status: 'analysis_ready' })

    const { result } = renderHook(() => useChatFlow())

    act(() => { result.current.send('What changed?') })
    expect(result.current.state).toBe('sending')

    await waitFor(() => expect(result.current.state).toBe('analysing'))
    expect(result.current.analysing?.conditionId).toBe('4')

    // Advance timers to trigger polls
    await act(async () => { vi.advanceTimersByTime(2000) })
    await act(async () => { vi.advanceTimersByTime(2000) })
    await act(async () => { vi.advanceTimersByTime(2000) })

    await waitFor(() => expect(result.current.state).toBe('answered'), { timeout: 5000 })
  })

  it('handles a fresh backend: 202 ingesting → status ready → resend → 202 analysing → analysis_ready → resend → answered', async () => {
    mockedPostChat
      .mockResolvedValueOnce({ type: 'analysing', status: 202, data: { status: 'ingesting', message: 'Preparing the DAQ inventory. Retry shortly.' } })
      .mockResolvedValueOnce(ANALYSING_RESPONSE)
      .mockResolvedValueOnce(READY_RESPONSE)
    mockedGetChatStatus
      .mockResolvedValueOnce({ status: 'ingesting' })
      .mockResolvedValueOnce({ status: 'ready' })
      .mockResolvedValueOnce({ status: 'analysing' })
      .mockResolvedValueOnce({ status: 'analysis_ready' })

    const { result } = renderHook(() => useChatFlow())
    act(() => { result.current.send('What changed in spindle vibration for condition 4?') })

    await waitFor(() => expect(result.current.analysing?.phase).toBe('ingesting'))
    expect(result.current.analysing?.conditionId).toBeNull()

    await waitFor(() => expect(result.current.analysing?.phase).toBe('analysing'), { timeout: 5000 })
    expect(result.current.analysing?.conditionId).toBe('4')

    await waitFor(() => expect(result.current.state).toBe('answered'), { timeout: 8000 })
    expect(mockedPostChat).toHaveBeenCalledTimes(3)
  }, 15_000)

  it('gives up with an error instead of resending forever', async () => {
    mockedPostChat.mockResolvedValue(ANALYSING_RESPONSE)
    mockedGetChatStatus.mockResolvedValue({ status: 'ready' })

    const { result } = renderHook(() => useChatFlow())
    act(() => { result.current.send('What changed in spindle vibration for condition 4?') })

    await waitFor(() => expect(result.current.state).toBe('error'), { timeout: 20_000 })
    expect(result.current.error?.message).toMatch(/kept deferring/)
    expect(mockedPostChat).toHaveBeenCalledTimes(6) // initial + MAX_RESENDS
  }, 25_000)

  it('transitions to error on 503', async () => {
    const { ApiError } = await import('../../api/client')
    mockedPostChat.mockRejectedValueOnce(new ApiError(503, { detail: 'overloaded' }, 'Service Unavailable'))

    const { result } = renderHook(() => useChatFlow())
    act(() => { result.current.send('test') })

    await waitFor(() => expect(result.current.state).toBe('error'))
    expect(result.current.error?.code).toBe(503)
    expect(result.current.error?.message).toContain('language model')
  })

  it('transitions to error on network failure', async () => {
    const { NetworkError } = await import('../../api/client')
    mockedPostChat.mockRejectedValueOnce(new NetworkError('http://localhost:8000/chat', new Error('connection refused')))

    const { result } = renderHook(() => useChatFlow())
    act(() => { result.current.send('test') })

    await waitFor(() => expect(result.current.state).toBe('error'))
    expect(result.current.error?.message).toContain("Can't reach the chat server")
  })

  it('cancel stops polling and returns to idle', async () => {
    mockedPostChat.mockResolvedValueOnce(ANALYSING_RESPONSE)
    mockedGetChatStatus.mockResolvedValue({ status: 'analysing' })

    const { result } = renderHook(() => useChatFlow())
    act(() => { result.current.send('test') })

    await waitFor(() => expect(result.current.state).toBe('analysing'))
    act(() => { result.current.cancel() })
    expect(result.current.state).toBe('idle')
  })

  it('retry re-sends the last question', async () => {
    const { ApiError } = await import('../../api/client')
    mockedPostChat
      .mockRejectedValueOnce(new ApiError(503, {}, 'fail'))
      .mockResolvedValueOnce(READY_RESPONSE)

    const { result } = renderHook(() => useChatFlow())
    act(() => { result.current.send('retryable question') })

    await waitFor(() => expect(result.current.state).toBe('error'))
    act(() => { result.current.retry() })

    await waitFor(() => expect(result.current.state).toBe('answered'))
    expect(mockedPostChat).toHaveBeenCalledTimes(2)
  })
})
