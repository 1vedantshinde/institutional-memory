/**
 * Explicit state machine for the Ask chat flow.
 *
 * States:
 *   idle          → ready for a new question
 *   sending       → POST /chat in flight
 *   analysing     → 202 received; polling GET /chat/status. The backend may be
 *                   "ingesting" (preparing the DAQ inventory) or "analysing" a scope.
 *   resending     → status left ingesting/analysing; re-POSTing the original question.
 *                   A resend can return another 202 (e.g. ingesting → analysing),
 *                   which goes back to analysing, up to MAX_RESENDS times.
 *   answered      → 200 received; answer rendered
 *   error         → any error state (LLM overload, network, timeout)
 *   timeout       → polling exceeded 10 minutes
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { postChat } from '../../api/chat'
import { getChatStatus } from '../../api/chat'
import { ApiError, NetworkError, TimeoutError } from '../../api/client'
import type { Citation, ChatAnalysingResponse } from '../../api/schemas'
import { addMessage, updateMessage, addEvidence } from '../../store/sessionStore'
import { parsePath } from '../../lib/parsePath'

export type FlowState =
  | 'idle'
  | 'sending'
  | 'analysing'
  | 'resending'
  | 'answered'
  | 'error'
  | 'timeout'

export interface AnalysingMeta {
  /** "ingesting" = DAQ inventory being prepared; "analysing" = scoped analysis running */
  phase: 'ingesting' | 'analysing'
  conditionId: string | null
  channel: string | null
  message: string
}

export interface ErrorMeta {
  code: number | null
  message: string
  detail: string | null
  retryable: boolean
}

interface UseChatFlowReturn {
  state: FlowState
  analysing: AnalysingMeta | null
  error: ErrorMeta | null
  elapsedMs: number
  send: (question: string) => void
  cancel: () => void
  retry: () => void
  reset: () => void
}

const POLL_INTERVAL_MS = 2_000
const TIMEOUT_MS = 10 * 60 * 1_000 // 10 minutes
// ingesting → analysing → answer needs 2 resends; allow headroom, never loop forever
const MAX_RESENDS = 5
// /chat/status values meaning "still working, keep polling"; anything else → resend
const PENDING_STATUSES = new Set(['ingesting', 'analysing'])

class ChatFlowError extends Error {
  name = 'ChatFlowError'
}

function toMeta(data: ChatAnalysingResponse, previous: AnalysingMeta | null): AnalysingMeta {
  const ingesting = data.status === 'ingesting'
  return {
    phase: ingesting ? 'ingesting' : 'analysing',
    conditionId: data.condition_id ?? previous?.conditionId ?? null,
    channel: data.channel ?? previous?.channel ?? null,
    message:
      data.message ??
      (ingesting ? 'Preparing the DAQ inventory.' : 'Analysing the requested signal.'),
  }
}

function classifyError(err: unknown): ErrorMeta {
  if (err instanceof ApiError) {
    if (err.status === 503) {
      return {
        code: 503,
        message: 'The language model is busy or not configured. Analytics are fine; try again shortly.',
        detail: typeof err.body === 'object' && err.body !== null
          ? JSON.stringify(err.body)
          : String(err.body),
        retryable: true,
      }
    }
    if (err.status === 400) {
      return {
        code: 400,
        message: 'The server could not process this question. Check your input.',
        detail: typeof err.body === 'object' && err.body !== null
          ? JSON.stringify(err.body)
          : String(err.body),
        retryable: false,
      }
    }
    return {
      code: err.status,
      message: err.message,
      detail: JSON.stringify(err.body),
      retryable: err.status >= 500,
    }
  }
  if (err instanceof NetworkError) {
    const url = localStorage.getItem('daq:chatApiUrl') ?? import.meta.env.VITE_CHAT_API_URL ?? 'http://localhost:8000'
    return {
      code: null,
      message: `Can't reach the chat server at ${url}`,
      detail: err.message,
      retryable: true,
    }
  }
  if (err instanceof ChatFlowError) {
    return { code: null, message: err.message, detail: null, retryable: true }
  }
  if (err instanceof TimeoutError) {
    return {
      code: null,
      message: 'Request timed out. The server took too long to respond.',
      detail: err.message,
      retryable: true,
    }
  }
  return {
    code: null,
    message: 'An unexpected error occurred.',
    detail: String(err),
    retryable: true,
  }
}

export function useChatFlow(): UseChatFlowReturn {
  const [flowState, setFlowState] = useState<FlowState>('idle')
  const [analysing, setAnalysing] = useState<AnalysingMeta | null>(null)
  const [errorMeta, setErrorMeta] = useState<ErrorMeta | null>(null)
  const [elapsedMs, setElapsedMs] = useState(0)

  const pendingQuestion = useRef<string>('')
  const assistantMsgId = useRef<string>('')
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const elapsedTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const startTimeRef = useRef<number>(0)
  const cancelledRef = useRef(false)
  const abortRef = useRef<AbortController | null>(null)
  const resendCountRef = useRef(0)
  const analysingRef = useRef<AnalysingMeta | null>(null)
  const pollRef = useRef<(msgId: string) => void>(() => {})

  const stopElapsed = useCallback(() => {
    if (elapsedTimerRef.current) clearInterval(elapsedTimerRef.current)
  }, [])

  const startElapsed = useCallback(() => {
    stopElapsed()
    startTimeRef.current = Date.now()
    elapsedTimerRef.current = setInterval(() => {
      setElapsedMs(Date.now() - startTimeRef.current)
    }, 500)
  }, [stopElapsed])

  const stopPoll = useCallback(() => {
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current)
  }, [])

  const handleError = useCallback(
    (err: unknown, msgId: string) => {
      const meta = classifyError(err)
      setErrorMeta(meta)
      setFlowState('error')
      stopElapsed()
      stopPoll()
      updateMessage(msgId, {
        error: { code: meta.code, message: meta.message, detail: meta.detail },
        isLoading: false,
      })
    },
    [stopElapsed, stopPoll],
  )

  const finishWithAnswer = useCallback(
    (
      citations: Citation[],
      answer: string,
      findingCount: number,
      msgId: string,
    ) => {
      updateMessage(msgId, {
        content: answer,
        citations,
        findingCount,
        isLoading: false,
      })
      // Collect evidence
      const evidenceEntries = citations.map((c) => {
        const parsed = parsePath(c.source_path)
        return {
          citation: c,
          conditionId: parsed.conditionId,
          recordingNumber: parsed.recordingNumber,
          firstSeenAt: new Date(),
          messageId: msgId,
        }
      })
      addEvidence(evidenceEntries)
      setFlowState('answered')
      stopElapsed()
    },
    [stopElapsed],
  )

  // 202 from POST /chat (initial or resend): show progress and poll /chat/status
  const handlePending = useCallback((data: ChatAnalysingResponse, msgId: string) => {
    const meta = toMeta(data, analysingRef.current)
    analysingRef.current = meta
    setAnalysing(meta)
    updateMessage(msgId, { content: meta.message })
    setFlowState('analysing')
    pollTimerRef.current = setTimeout(() => pollRef.current(msgId), POLL_INTERVAL_MS)
  }, [])

  const resend = useCallback(
    (msgId: string) => {
      resendCountRef.current += 1
      if (resendCountRef.current > MAX_RESENDS) {
        handleError(
          new ChatFlowError('The server kept deferring this question. Check the backend logs, then retry.'),
          msgId,
        )
        return
      }
      setFlowState('resending')
      postChat(pendingQuestion.current, abortRef.current?.signal)
        .then((res) => {
          if (cancelledRef.current) return
          if (res.type === 'ready') {
            finishWithAnswer(res.data.citations, res.data.answer, res.data.finding_count, msgId)
          } else {
            handlePending(res.data, msgId)
          }
        })
        .catch((err) => {
          if (!cancelledRef.current) handleError(err, msgId)
        })
    },
    [finishWithAnswer, handleError, handlePending],
  )

  const pollStatus = useCallback(
    (msgId: string) => {
      if (cancelledRef.current) return

      // Timeout guard
      if (Date.now() - startTimeRef.current >= TIMEOUT_MS) {
        setFlowState('timeout')
        stopElapsed()
        updateMessage(msgId, { isLoading: false })
        return
      }

      getChatStatus()
        .then((status) => {
          if (cancelledRef.current) return
          if (PENDING_STATUSES.has(status.status)) {
            const phase = status.status === 'ingesting' ? 'ingesting' : 'analysing'
            if (analysingRef.current && analysingRef.current.phase !== phase) {
              analysingRef.current = { ...analysingRef.current, phase }
              setAnalysing(analysingRef.current)
            }
            pollTimerRef.current = setTimeout(() => pollRef.current(msgId), POLL_INTERVAL_MS)
          } else {
            // analysis_ready, ready, or unknown: re-ask; the server says what's next
            resend(msgId)
          }
        })
        .catch((err) => {
          if (!cancelledRef.current) handleError(err, msgId)
        })
    },
    [handleError, resend, stopElapsed],
  )
  pollRef.current = pollStatus

  const send = useCallback(
    (question: string) => {
      if (flowState !== 'idle' && flowState !== 'answered' && flowState !== 'error' && flowState !== 'timeout') return
      cancelledRef.current = false
      resendCountRef.current = 0
      analysingRef.current = null
      pendingQuestion.current = question
      abortRef.current = new AbortController()

      // Add user message
      addMessage({ role: 'user', content: question, timestamp: new Date() })

      // Add placeholder assistant message
      const msgId = addMessage({
        role: 'assistant',
        content: '',
        timestamp: new Date(),
        isLoading: true,
      })
      assistantMsgId.current = msgId

      setFlowState('sending')
      setErrorMeta(null)
      setElapsedMs(0)
      startElapsed()

      postChat(question, abortRef.current.signal)
        .then((res) => {
          if (cancelledRef.current) return
          if (res.type === 'ready') {
            finishWithAnswer(res.data.citations, res.data.answer, res.data.finding_count, msgId)
          } else {
            handlePending(res.data, msgId)
          }
        })
        .catch((err) => {
          if (!cancelledRef.current) handleError(err, msgId)
        })
    },
    [flowState, startElapsed, finishWithAnswer, handlePending, handleError],
  )

  const cancel = useCallback(() => {
    cancelledRef.current = true
    abortRef.current?.abort()
    stopPoll()
    stopElapsed()
    setFlowState('idle')
    setAnalysing(null)
    if (assistantMsgId.current) {
      updateMessage(assistantMsgId.current, { isLoading: false, content: '(cancelled)' })
    }
  }, [stopPoll, stopElapsed])

  const retry = useCallback(() => {
    if (pendingQuestion.current) {
      setFlowState('idle')
      setErrorMeta(null)
      send(pendingQuestion.current)
    }
  }, [send])

  const reset = useCallback(() => {
    cancelledRef.current = true
    abortRef.current?.abort()
    stopPoll()
    stopElapsed()
    setFlowState('idle')
    setAnalysing(null)
    setErrorMeta(null)
    setElapsedMs(0)
    pendingQuestion.current = ''
  }, [stopPoll, stopElapsed])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      cancelledRef.current = true
      stopPoll()
      stopElapsed()
    }
  }, [stopPoll, stopElapsed])

  return {
    state: flowState,
    analysing,
    error: errorMeta,
    elapsedMs,
    send,
    cancel,
    retry,
    reset,
  }
}
