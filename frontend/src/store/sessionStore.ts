import { newId } from '../lib/id'
/**
 * In-memory + sessionStorage store for chat messages and collected citations.
 * Using a simple reactive pattern with event listeners instead of a heavy
 * state library — the state never needs to cross component trees beyond
 * what React context provides.
 */

import type { Citation, DocumentSource } from '../api/schemas'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  /** Knowledge-document passages cited as [Source N] (general questions) */
  sources?: DocumentSource[]
  findingCount?: number
  timestamp: Date
  error?: {
    code: number | null
    message: string
    detail: string | null
  }
  isLoading?: boolean
}

export interface SessionEvidence {
  citation: Citation
  conditionId: string | null
  recordingNumber: string | null
  firstSeenAt: Date
  messageId: string
}

const STORAGE_KEY = 'daq:session'

// ─── Settings ────────────────────────────────────────────────────────────────

export interface AppSettings {
  chatApiUrl: string
  coreApiUrl: string
  datasetPath: string
  configPath: string
  theme: 'dark' | 'light'
  simulateLlmOverload: boolean
}

function defaultSettings(): AppSettings {
  return {
    chatApiUrl: import.meta.env.VITE_CHAT_API_URL ?? 'http://localhost:8000',
    coreApiUrl: import.meta.env.VITE_CORE_API_URL ?? 'http://localhost:8001',
    datasetPath: import.meta.env.VITE_DEFAULT_DATASET_PATH ?? 'dataset/Readngs_DAQ_Data',
    configPath: import.meta.env.VITE_DEFAULT_CONFIG_PATH ?? 'config/domain.yaml',
    theme: 'dark',
    simulateLlmOverload: false,
  }
}

function loadSettings(): AppSettings {
  try {
    const raw = localStorage.getItem('daq:settings')
    if (!raw) return defaultSettings()
    return { ...defaultSettings(), ...JSON.parse(raw) }
  } catch {
    return defaultSettings()
  }
}

function saveSettings(s: AppSettings): void {
  try {
    localStorage.setItem('daq:settings', JSON.stringify(s))
    localStorage.setItem('daq:chatApiUrl', s.chatApiUrl)
    localStorage.setItem('daq:coreApiUrl', s.coreApiUrl)
    localStorage.setItem('daq:simulateLlmOverload', String(s.simulateLlmOverload))
  } catch {}
}

// ─── Session state ────────────────────────────────────────────────────────────

interface SessionState {
  messages: ChatMessage[]
  evidence: SessionEvidence[]
  settings: AppSettings
}

function loadSession(): SessionState {
  const settings = loadSettings()
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      // Rehydrate Date objects
      const messages: ChatMessage[] = (parsed.messages ?? []).map((m: ChatMessage) => ({
        ...m,
        timestamp: new Date(m.timestamp),
      }))
      const evidence: SessionEvidence[] = (parsed.evidence ?? []).map((e: SessionEvidence) => ({
        ...e,
        firstSeenAt: new Date(e.firstSeenAt),
      }))
      return { messages, evidence, settings }
    }
  } catch {}
  return { messages: [], evidence: [], settings }
}

let state: SessionState = loadSession()

function persist() {
  try {
    sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        messages: state.messages,
        evidence: state.evidence,
      }),
    )
  } catch {}
}

// ─── Listeners ────────────────────────────────────────────────────────────────

type Listener = () => void
const listeners = new Set<Listener>()

function notify() {
  listeners.forEach((l) => l())
  persist()
}

export function subscribe(fn: Listener): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

// ─── Message helpers ──────────────────────────────────────────────────────────

export function getMessages(): ChatMessage[] {
  return state.messages
}

export function addMessage(msg: Omit<ChatMessage, 'id'> & { id?: string }): string {
  const id = msg.id ?? newId()
  state.messages = [...state.messages, { ...msg, id }]
  notify()
  return id
}

export function updateMessage(id: string, patch: Partial<ChatMessage>): void {
  state.messages = state.messages.map((m) => (m.id === id ? { ...m, ...patch } : m))
  notify()
}

export function clearMessages(): void {
  state.messages = []
  notify()
}

// ─── Evidence helpers ─────────────────────────────────────────────────────────

export function getEvidence(): SessionEvidence[] {
  return state.evidence
}

export function addEvidence(entries: SessionEvidence[]): void {
  const existing = new Set(state.evidence.map((e) => e.citation.finding_id))
  const fresh = entries.filter((e) => !existing.has(e.citation.finding_id))
  if (fresh.length > 0) {
    state.evidence = [...state.evidence, ...fresh]
    notify()
  }
}

// ─── Settings helpers ─────────────────────────────────────────────────────────

export function getSettings(): AppSettings {
  return state.settings
}

export function updateSettings(patch: Partial<AppSettings>): void {
  state.settings = { ...state.settings, ...patch }
  saveSettings(state.settings)
  notify()
}
