import type { ReactElement } from 'react'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { act } from '@testing-library/react'
import { vi } from 'vitest'
import { TooltipProvider } from '@/components/ui/tooltip'

/** Renders a page with the same providers App.tsx uses, plus a location probe. */
export function renderPage(ui: ReactElement, { path = '/page' } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const location = { current: '' }
  function LocationProbe() {
    const loc = useLocation()
    location.current = loc.pathname + loc.search
    return null
  }
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="*" element={<>{ui}<LocationProbe /></>} />
          </Routes>
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  )
  return { ...utils, queryClient, location }
}

/**
 * Advances fake timers in 500 ms steps (flushing MSW delays and TanStack
 * refetchInterval polls) until `check` stops throwing.
 */
export async function advanceUntil(check: () => void, maxMs = 30_000): Promise<void> {
  for (let t = 0; ; t += 500) {
    try {
      check()
      return
    } catch (err) {
      if (t >= maxMs) throw err
    }
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500)
    })
  }
}
