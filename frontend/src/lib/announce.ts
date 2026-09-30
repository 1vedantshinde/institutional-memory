/**
 * Announces a status change to screen readers via the polite live region
 * rendered by Layout (#live-announcer).
 */
export function announce(message: string): void {
  const el = document.getElementById('live-announcer')
  if (!el) return
  // Clear first so repeating the same message is still announced
  el.textContent = ''
  window.setTimeout(() => { el.textContent = message }, 50)
}

export function prefersReducedMotion(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}
