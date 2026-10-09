import { http, HttpResponse, delay } from 'msw'
import {
  MOCK_CHAT_INGESTING,
  MOCK_CHAT_ANALYSING,
  MOCK_CHAT_READY,
  MOCK_CHAT_DOCUMENTS_ANSWER,
  MOCK_CHAT_STATUS_ANALYSING,
  MOCK_CHAT_STATUS_READY,
  MOCK_PROFILE_RUNNING,
  MOCK_PROFILE_COMPLETE,
  MOCK_ANALYSIS_STATUS_RUNNING,
  MOCK_ANALYSIS_STATUS_COMPLETE,
  MOCK_CONFIG,
  MOCK_CONDITIONS,
  MOCK_FINDINGS,
  MOCK_TOOL_WEAR,
} from './fixtures'

// /chat mirrors server.py on a fresh backend:
//   POST → 202 ingesting; status: ingesting, then ready
//   POST → 202 analysing; status: analysing ×2, then analysis_ready
//   POST → 200 answer
let chatCallCount = 0
let statusCallCount = 0
let chatPhase: 'idle' | 'ingesting' | 'analysing' = 'idle'
let profileCallCount = 0
let analyseStatusCallCount = 0

/** Resets the call-sequence counters above. Called between tests. */
export function resetMockState(): void {
  chatCallCount = 0
  statusCallCount = 0
  chatPhase = 'idle'
  profileCallCount = 0
  analyseStatusCallCount = 0
}

// Settings can toggle LLM overload simulation
function isSimulatingOverload(): boolean {
  try {
    return localStorage.getItem('daq:simulateLlmOverload') === 'true'
  } catch {
    return false
  }
}

const CHAT_URL = import.meta.env.VITE_CHAT_API_URL ?? 'http://localhost:8000'
const CORE_URL = import.meta.env.VITE_CORE_API_URL ?? 'http://localhost:8001'

export const handlers = [
  // ── Chat server ────────────────────────────────────────────────────────────

  http.post(`${CHAT_URL}/chat`, async ({ request }) => {
    await delay(400)
    if (isSimulatingOverload()) {
      return HttpResponse.json(
        { detail: 'Language model temporarily unavailable. Analytics are unaffected. Please retry shortly.' },
        { status: 503 },
      )
    }
    // Like server.py: without a condition number the question goes to the
    // project knowledge documents instead of the DAQ findings.
    const { question = '' } = ((await request.json().catch(() => ({}))) ?? {}) as { question?: string }
    if (!/condition\s*\d+/i.test(question)) {
      return HttpResponse.json(MOCK_CHAT_DOCUMENTS_ANSWER, { status: 200 })
    }
    chatCallCount++
    statusCallCount = 0
    if (chatCallCount === 1) {
      chatPhase = 'ingesting'
      return HttpResponse.json(MOCK_CHAT_INGESTING, { status: 202 })
    }
    if (chatCallCount === 2) {
      chatPhase = 'analysing'
      return HttpResponse.json(MOCK_CHAT_ANALYSING, { status: 202 })
    }
    // Auto-reset for repeated demos
    chatCallCount = 0
    chatPhase = 'idle'
    return HttpResponse.json(MOCK_CHAT_READY, { status: 200 })
  }),

  http.get(`${CHAT_URL}/chat/status`, async () => {
    await delay(200)
    statusCallCount++
    if (chatPhase === 'ingesting') {
      return HttpResponse.json(statusCallCount <= 1 ? { status: 'ingesting' } : { status: 'ready' })
    }
    if (chatPhase === 'analysing' && statusCallCount <= 2) {
      return HttpResponse.json(MOCK_CHAT_STATUS_ANALYSING)
    }
    return HttpResponse.json(MOCK_CHAT_STATUS_READY)
  }),

  // ── Core API ───────────────────────────────────────────────────────────────

  http.post(`${CORE_URL}/ingest`, async () => {
    await delay(300)
    profileCallCount = 0
    return HttpResponse.json({ status: 'accepted', message: 'Profile pass started.' }, { status: 202 })
  }),

  http.get(`${CORE_URL}/profile`, async () => {
    await delay(300)
    profileCallCount++
    if (profileCallCount === 1) {
      return HttpResponse.json(MOCK_PROFILE_RUNNING)
    }
    return HttpResponse.json(MOCK_PROFILE_COMPLETE)
  }),

  // Mirrors api/main.py: "idle" until a job starts, "running" for two polls,
  // then "complete" until the next POST; 409 while a job is running.
  http.post(`${CORE_URL}/analyse`, async () => {
    await delay(300)
    if (analyseStatusCallCount > 0 && analyseStatusCallCount <= 3) {
      return HttpResponse.json({ detail: 'DAQ analysis is already running.' }, { status: 409 })
    }
    analyseStatusCallCount = 1
    return HttpResponse.json({ status: 'running', analysis_status_url: '/analyse/status' }, { status: 202 })
  }),

  http.get(`${CORE_URL}/analyse/status`, async () => {
    await delay(300)
    if (analyseStatusCallCount === 0) return HttpResponse.json({ status: 'idle' })
    analyseStatusCallCount++
    if (analyseStatusCallCount <= 3) {
      return HttpResponse.json(MOCK_ANALYSIS_STATUS_RUNNING)
    }
    return HttpResponse.json(MOCK_ANALYSIS_STATUS_COMPLETE)
  }),

  http.post(`${CORE_URL}/query`, async () => {
    await delay(500)
    if (isSimulatingOverload()) {
      return HttpResponse.json({ detail: 'LLM not configured.' }, { status: 503 })
    }
    return HttpResponse.json(MOCK_CHAT_READY)
  }),

  http.get(`${CORE_URL}/config`, async () => {
    await delay(200)
    return HttpResponse.json(MOCK_CONFIG)
  }),

  http.put(`${CORE_URL}/config`, async () => {
    await delay(300)
    return HttpResponse.json({ status: 'ok', message: 'Config hot-reloaded.' })
  }),

  // ── Proposed endpoints (only active when VITE_ENABLE_PROPOSED=true) ────────

  http.get(`${CORE_URL}/conditions`, async () => {
    await delay(200)
    return HttpResponse.json(MOCK_CONDITIONS)
  }),

  http.get(`${CORE_URL}/findings`, async () => {
    await delay(300)
    return HttpResponse.json(MOCK_FINDINGS)
  }),

  http.get(`${CORE_URL}/recordings/:id/windows/:windowId/signal`, async () => {
    await delay(400)
    const samples = Array.from({ length: 2048 }, (_, i) =>
      Math.sin(i * 0.05) * 2 + Math.sin(i * 0.13) * 0.5 + (Math.random() - 0.5) * 0.3,
    )
    return HttpResponse.json({
      window_id: 'win-12-004',
      channel: 'Vib_Spindle',
      samples,
      sample_rate: 10000,
      sample_start: 4096,
    })
  }),

  http.get(`${CORE_URL}/tool-wear/evaluation`, async () => {
    await delay(200)
    return HttpResponse.json(MOCK_TOOL_WEAR)
  }),
]
