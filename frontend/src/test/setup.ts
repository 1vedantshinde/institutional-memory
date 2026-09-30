import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeAll, afterAll, vi } from 'vitest'
import { server } from '@/mocks/server'
import { resetMockState } from '@/mocks/handlers'

// ─── Storage + crypto mocks ──────────────────────────────────────────────────

function createStorageMock(): Storage {
  const store: Record<string, string> = {}
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = String(value) },
    removeItem: (key: string) => { delete store[key] },
    clear: () => { Object.keys(store).forEach((k) => delete store[k]) },
    get length() { return Object.keys(store).length },
    key: (i: number) => Object.keys(store)[i] ?? null,
  }
}

Object.defineProperty(window, 'localStorage', { value: createStorageMock() })
Object.defineProperty(window, 'sessionStorage', { value: createStorageMock() })

if (!crypto.randomUUID) {
  Object.defineProperty(crypto, 'randomUUID', {
    value: () => Math.random().toString(36).slice(2) + Date.now().toString(36),
  })
}

// jsdom lacks ResizeObserver (used by Radix Slider and Recharts ResponsiveContainer)
if (!('ResizeObserver' in globalThis)) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
}

// ─── MSW server lifecycle ────────────────────────────────────────────────────

// 'error' makes any request without a handler fail loudly instead of
// silently hitting the real network.
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  cleanup()
  server.resetHandlers()
  resetMockState()
  localStorage.clear()
  sessionStorage.clear()
})
afterAll(() => server.close())

// Silence MSW / app info logging in test output
vi.spyOn(console, 'info').mockImplementation(() => {})
