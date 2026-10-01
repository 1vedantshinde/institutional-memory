import { chatGet, ApiError, NetworkError, TimeoutError, errorMessage, LLM_ANSWER_TIMEOUT_MS } from './client'
import {
  ChatReadyResponseSchema,
  ChatAnalysingResponseSchema,
  ChatStatusResponseSchema,
  type ChatReadyResponse,
  type ChatAnalysingResponse,
  type ChatStatusResponse,
} from './schemas'

export type ChatResponse =
  | { type: 'ready'; data: ChatReadyResponse; status: 200 }
  | { type: 'analysing'; data: ChatAnalysingResponse; status: 202 }

export async function postChat(question: string, signal?: AbortSignal): Promise<ChatResponse> {
  // We need to inspect the status code, so we do raw fetch here
  const chatUrl = (localStorage.getItem('daq:chatApiUrl') ?? import.meta.env.VITE_CHAT_API_URL ?? 'http://localhost:8000').replace(/\/$/, '')

  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), LLM_ANSWER_TIMEOUT_MS)
  const combinedSignal = signal
    ? (() => {
        const ctrl = new AbortController()
        signal.addEventListener('abort', () => ctrl.abort())
        controller.signal.addEventListener('abort', () => ctrl.abort())
        return ctrl.signal
      })()
    : controller.signal

  const url = `${chatUrl}/chat`
  let res: Response
  try {
    res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ question }),
      signal: combinedSignal,
    })
  } catch (err) {
    clearTimeout(timeout)
    // Our own 30 s timer fired (a caller-initiated abort is a cancel, not a timeout)
    if (controller.signal.aborted && !signal?.aborted) throw new TimeoutError(url, LLM_ANSWER_TIMEOUT_MS)
    throw new NetworkError(url, err)
  }

  try {
    // Proxies and overloaded servers may answer 5xx with a non-JSON body
    const text = await res.text()
    let body: unknown = text
    try {
      body = text ? JSON.parse(text) : null
    } catch {
      /* keep raw text */
    }

    if (res.status === 200) {
      return { type: 'ready', data: ChatReadyResponseSchema.parse(body), status: 200 }
    }
    if (res.status === 202) {
      return { type: 'analysing', data: ChatAnalysingResponseSchema.parse(body), status: 202 }
    }

    // Re-throw as ApiError for 400, 503, etc.
    throw new ApiError(res.status, body, errorMessage(res.status, body))
  } finally {
    clearTimeout(timeout)
  }
}

export async function getChatStatus(): Promise<ChatStatusResponse> {
  const raw = await chatGet<unknown>('/chat/status', { timeoutMs: 8_000 })
  return ChatStatusResponseSchema.parse(raw)
}
