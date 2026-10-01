/**
 * Adapters that normalize responses whose exact field names are not fully
 * specified. Each adapter tries several plausible key names.
 *
 * ADJUST: Once the real backend response shapes are confirmed, update the
 * key aliases in normalizeProfile() and normalizeAnalysisStatus() to match
 * the actual field names and remove the fallback aliases that no longer apply.
 */

import type { RawProfile, RawAnalysisStatus } from './schemas'

export interface NormalizedProfile {
  status: string
  discovered: number | null
  canonical: number | null
  quarantined: number | null
  reasons: Record<string, number>
  raw: RawProfile
}

export interface NormalizedAnalysisStatus {
  status: string
  message: string | null
  modelVersion: string | null
  error: string | null
  raw: RawAnalysisStatus
}

function first<T>(...values: Array<T | undefined | null>): T | null {
  for (const v of values) {
    if (v != null) return v
  }
  return null
}

export function normalizeProfile(raw: RawProfile): NormalizedProfile {
  // Summary may be nested under a "summary" key
  const s = raw.summary ?? raw

  const discovered = first(
    s.discovered,
    s.total,
    s.discovered_count,
  )
  const canonical = first(s.canonical, s.canonical_count)
  const quarantined = first(s.quarantined, s.quarantined_count)

  const reasons: Record<string, number> =
    s.by_reason ?? s.reasons ?? s.reason_counts ?? s.per_reason ?? {}

  return {
    status: raw.status ?? 'unknown',
    discovered,
    canonical,
    quarantined,
    reasons,
    raw,
  }
}

export function normalizeAnalysisStatus(raw: RawAnalysisStatus): NormalizedAnalysisStatus {
  return {
    status: raw.status ?? 'unknown',
    message: raw.message ?? null,
    modelVersion: raw.model_version ?? null,
    error: raw.error ?? null,
    raw,
  }
}
