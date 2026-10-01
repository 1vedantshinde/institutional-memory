import { describe, it, expect } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/mocks/server'
import { pingChat, pingCore } from './client'

describe('health pings', () => {
  it('treat an HTTP error response as reachable (GET /profile is 404 before the first ingest)', async () => {
    server.use(http.get('http://localhost:8001/profile', () =>
      HttpResponse.json({ detail: 'No DAQ ingest run is available.' }, { status: 404 })))
    expect(await pingCore()).toBe(true)
  })

  it('report unreachable when the connection fails', async () => {
    server.use(
      http.get('http://localhost:8001/profile', () => HttpResponse.error()),
      http.get('http://localhost:8000/chat/status', () => HttpResponse.error()),
    )
    expect(await pingCore()).toBe(false)
    expect(await pingChat()).toBe(false)
  })
})
