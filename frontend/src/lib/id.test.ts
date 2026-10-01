import { describe, it, expect, vi, afterEach } from 'vitest'
import { newId } from './id'

afterEach(() => { vi.unstubAllGlobals() })

describe('newId', () => {
  it('works when crypto.randomUUID is missing (plain-HTTP LAN address)', () => {
    vi.stubGlobal('crypto', { getRandomValues: globalThis.crypto.getRandomValues.bind(globalThis.crypto) })
    const a = newId()
    const b = newId()
    expect(a).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
    expect(a).not.toBe(b)
  })
})
