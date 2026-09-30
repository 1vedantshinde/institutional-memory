import { z } from 'zod'

// ─── Shared ──────────────────────────────────────────────────────────────────

export const SampleRangeSchema = z.object({
  sample_start: z.number().int(),
  sample_end: z.number().int(),
})

export const CitationSchema = z.object({
  label: z.string(),
  finding_id: z.string(),
  model_version: z.string(),
  source_path: z.string(),
  channel: z.string(),
  window_id: z.string(),
  sample_range: SampleRangeSchema,
  time_range: z
    .object({ time_start: z.number(), time_end: z.number() })
    .nullable()
    .optional(),
})

export type Citation = z.infer<typeof CitationSchema>

// ─── Chat server ─────────────────────────────────────────────────────────────

export const ChatReadyResponseSchema = z.object({
  answer: z.string(),
  citations: z.array(CitationSchema),
  finding_count: z.number(),
})
export type ChatReadyResponse = z.infer<typeof ChatReadyResponseSchema>

// HTTP 202 from POST /chat. server.py sends two shapes:
//   {status: "ingesting", message}                          — DAQ inventory being prepared (no scope yet)
//   {status: "analysing", condition_id, channel, message, status_url}
export const ChatAnalysingResponseSchema = z
  .object({
    status: z.string(),
    condition_id: z.string().optional(),
    channel: z.string().optional(),
    message: z.string().optional(),
    status_url: z.string().optional(),
  })
  .passthrough()
export type ChatAnalysingResponse = z.infer<typeof ChatAnalysingResponseSchema>

export const ChatStatusResponseSchema = z
  .object({
    status: z.string(), // "analysis_ready" | "analysing" | others
  })
  .passthrough()
export type ChatStatusResponse = z.infer<typeof ChatStatusResponseSchema>

// ─── Core API ─────────────────────────────────────────────────────────────────

// POST /ingest
export const IngestResponseSchema = z
  .object({ status: z.string().optional(), message: z.string().optional() })
  .passthrough()

// GET /profile — defensive: accept many plausible key names
export const RawProfileSchema = z
  .object({
    status: z.string().optional(),
    // allow many key aliases
    discovered: z.number().optional(),
    total: z.number().optional(),
    discovered_count: z.number().optional(),
    canonical: z.number().optional(),
    canonical_count: z.number().optional(),
    quarantined: z.number().optional(),
    quarantined_count: z.number().optional(),
    by_reason: z.record(z.string(), z.number()).optional(),
    reasons: z.record(z.string(), z.number()).optional(),
    reason_counts: z.record(z.string(), z.number()).optional(),
    per_reason: z.record(z.string(), z.number()).optional(),
    summary: z
      .object({
        discovered: z.number().optional(),
        total: z.number().optional(),
        discovered_count: z.number().optional(),
        canonical: z.number().optional(),
        canonical_count: z.number().optional(),
        quarantined: z.number().optional(),
        quarantined_count: z.number().optional(),
        by_reason: z.record(z.string(), z.number()).optional(),
        reasons: z.record(z.string(), z.number()).optional(),
        reason_counts: z.record(z.string(), z.number()).optional(),
        per_reason: z.record(z.string(), z.number()).optional(),
      })
      .optional(),
  })
  .passthrough()

export type RawProfile = z.infer<typeof RawProfileSchema>

// GET /analyse/status — defensive
export const RawAnalysisStatusSchema = z
  .object({
    status: z.string().optional(),
    message: z.string().optional(),
    model_version: z.string().optional(),
    error: z.string().optional(),
  })
  .passthrough()

export type RawAnalysisStatus = z.infer<typeof RawAnalysisStatusSchema>

// POST /query — same response shape as chat 200
export const QueryResponseSchema = ChatReadyResponseSchema

// GET /config
export const ConfigResponseSchema = z.record(z.string(), z.unknown())
export type ConfigResponse = z.infer<typeof ConfigResponseSchema>
