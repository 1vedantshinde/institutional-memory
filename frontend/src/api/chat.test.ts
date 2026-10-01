import { describe, it, expect } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/mocks/server'
import { postChat, getChatStatus } from './chat'
import { ApiError, NetworkError } from './client'

const CHAT = 'http://localhost:8000'

describe('postChat (against MSW)', () => {
  it('follows the real server sequence: 202 ingesting → 202 analysing → 200', async () => {
    const q = 'What changed in spindle vibration for condition 4?'
    const first = await postChat(q)
    expect(first).toMatchObject({ type: 'analysing', data: { status: 'ingesting' } })
    expect((await getChatStatus()).status).toBe('ingesting')
    expect((await getChatStatus()).status).toBe('ready')

    const second = await postChat(q)
    expect(second).toMatchObject({ type: 'analysing', data: { status: 'analysing', condition_id: '4' } })
    expect((await getChatStatus()).status).toBe('analysing')
    expect((await getChatStatus()).status).toBe('analysing')
    expect((await getChatStatus()).status).toBe('analysis_ready')

    const third = await postChat(q)
    expect(third.type).toBe('ready')
    if (third.type === 'ready') {
      expect(third.data.citations).toHaveLength(2)
      expect(third.data.citations[1].time_range).toBeNull()
    }
  })

  it('accepts the exact ingesting body server.py sends (no condition_id/channel)', async () => {
    server.use(http.post(`${CHAT}/chat`, () =>
      HttpResponse.json({ status: 'ingesting', message: 'Preparing the DAQ inventory. Retry shortly.' }, { status: 202 })))
    await expect(postChat('q')).resolves.toMatchObject({ type: 'analysing', data: { status: 'ingesting' } })
  })

  it('surfaces the 422 guidance when the question lacks a condition or signal', async () => {
    const detail = "State both a condition and one signal, for example: 'Explain spindle vibration for condition 4.'"
    server.use(http.post(`${CHAT}/chat`, () => HttpResponse.json({ detail }, { status: 422 })))
    await expect(postChat('hello')).rejects.toMatchObject({ status: 422, message: detail })
  })

  it('throws ApiError(503) on LLM overload', async () => {
    localStorage.setItem('daq:simulateLlmOverload', 'true')
    await expect(postChat('q')).rejects.toMatchObject({ name: 'ApiError', status: 503 })
  })

  it('throws ApiError (not a JSON parse error) when a 503 body is plain text', async () => {
    server.use(http.post(`${CHAT}/chat`, () => new HttpResponse('Service Unavailable', { status: 503 })))
    const err = await postChat('q').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(503)
  })

  it('wraps a connection failure in NetworkError', async () => {
    server.use(http.post(`${CHAT}/chat`, () => HttpResponse.error()))
    await expect(postChat('q')).rejects.toBeInstanceOf(NetworkError)
  })
})
