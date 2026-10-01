/**
 * Typed fetch wrapper with timeouts and structured errors.
 * All API calls go through apiRequest(); callers should not use fetch() directly.
 */

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export class NetworkError extends Error {
  // Declared explicitly: tsconfig lib is ES2020, which predates Error.cause (ES2022)
  public readonly cause?: unknown

  constructor(
    public readonly url: string,
    cause: unknown,
  ) {
    super(`Network request failed: ${url}`)
    this.name = 'NetworkError'
    this.cause = cause
  }
}

export class TimeoutError extends Error {
  constructor(public readonly url: string, public readonly ms: number) {
    super(`Request timed out after ${ms}ms: ${url}`)
    this.name = 'TimeoutError'
  }
}

/**
 * Human-readable message from an error body. FastAPI puts it in `detail`
 * (a string, or a list of validation errors for 422); others use `message`.
 */
export function errorMessage(status: number, body: unknown): string {
  if (typeof body === 'object' && body !== null) {
    const b = body as Record<string, unknown>
    if (typeof b.message === 'string' && b.message) return b.message
    if (typeof b.detail === 'string' && b.detail) return b.detail
    if (Array.isArray(b.detail)) {
      const msgs = b.detail
        .map((d) => (typeof d === 'object' && d !== null && 'msg' in d ? String((d as { msg: unknown }).msg) : null))
        .filter(Boolean)
      if (msgs.length) return msgs.join('; ')
    }
  }
  if (typeof body === 'string' && body.trim() && body.length <= 200) return body.trim()
  return `HTTP ${status}`
}

/**
 * Timeout for requests that wait on the LLM (POST /chat once evidence is
 * ready, POST /query). Measured 11–35 s per answer on the real backend, and
 * ~184 s when the provider is overloaded and the backend retries 3 times
 * before returning its 503. Must outlast that so the user sees the backend's
 * "model unavailable" message instead of a generic timeout.
 */
export const LLM_ANSWER_TIMEOUT_MS = 300_000

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
  timeoutMs?: number
  signal?: AbortSignal
}

async function apiRequest<T = unknown>(url: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, timeoutMs = 30_000, signal } = options

  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), timeoutMs)

  // Merge caller signal with our timeout signal
  const combinedSignal = signal
    ? (() => {
        const ctrl = new AbortController()
        signal.addEventListener('abort', () => ctrl.abort())
        controller.signal.addEventListener('abort', () => ctrl.abort())
        return ctrl.signal
      })()
    : controller.signal

  try {
    const init: RequestInit = {
      method,
      signal: combinedSignal,
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
    }
    if (body !== undefined) {
      init.body = JSON.stringify(body)
    }

    const response = await fetch(url, init)

    const contentType = response.headers.get('content-type') ?? ''
    let responseBody: unknown
    if (contentType.includes('application/json')) {
      responseBody = await response.json()
    } else {
      responseBody = await response.text()
    }

    if (!response.ok) {
      throw new ApiError(response.status, responseBody, errorMessage(response.status, responseBody))
    }

    return responseBody as T
  } catch (err) {
    if (err instanceof ApiError) throw err
    if (err instanceof Error && err.name === 'AbortError') {
      throw new TimeoutError(url, timeoutMs)
    }
    throw new NetworkError(url, err)
  } finally {
    clearTimeout(timeout)
  }
}

// ─── URL factories ────────────────────────────────────────────────────────────

function getChatUrl(): string {
  const stored = localStorage.getItem('daq:chatApiUrl')
  return (stored ?? import.meta.env.VITE_CHAT_API_URL ?? 'http://localhost:8000').replace(/\/$/, '')
}

function getCoreUrl(): string {
  const stored = localStorage.getItem('daq:coreApiUrl')
  return (stored ?? import.meta.env.VITE_CORE_API_URL ?? 'http://localhost:8001').replace(/\/$/, '')
}

// ─── Exported request helpers ─────────────────────────────────────────────────

export function chatGet<T = unknown>(path: string, opts?: Omit<RequestOptions, 'method' | 'body'>): Promise<T> {
  return apiRequest<T>(`${getChatUrl()}${path}`, { ...opts, method: 'GET' })
}

export function chatPost<T = unknown>(path: string, body: unknown, opts?: Omit<RequestOptions, 'method'>): Promise<T> {
  return apiRequest<T>(`${getChatUrl()}${path}`, { ...opts, method: 'POST', body })
}

export function coreGet<T = unknown>(path: string, opts?: Omit<RequestOptions, 'method' | 'body'>): Promise<T> {
  return apiRequest<T>(`${getCoreUrl()}${path}`, { ...opts, method: 'GET' })
}

export function corePost<T = unknown>(path: string, body: unknown, opts?: Omit<RequestOptions, 'method'>): Promise<T> {
  return apiRequest<T>(`${getCoreUrl()}${path}`, { ...opts, method: 'POST', body })
}

export function corePut<T = unknown>(path: string, body: unknown, opts?: Omit<RequestOptions, 'method'>): Promise<T> {
  return apiRequest<T>(`${getCoreUrl()}${path}`, { ...opts, method: 'PUT', body })
}

// Cheap health-checks. Any HTTP response means the server is reachable:
// GET /profile answers 404 until the first ingest run, which is not an outage.
export async function pingChat(): Promise<boolean> {
  try {
    await chatGet('/chat/status', { timeoutMs: 5_000 })
    return true
  } catch (err) {
    return err instanceof ApiError
  }
}

export async function pingCore(): Promise<boolean> {
  try {
    await coreGet('/profile', { timeoutMs: 5_000 })
    return true
  } catch (err) {
    return err instanceof ApiError
  }
}
