/**
 * Proposed endpoints that do not yet exist in the backend.
 * These are only used when VITE_ENABLE_PROPOSED=true (MSW mocks only).
 *
 * BACKEND: See BACKEND_REQUESTS.md for the full spec of these endpoints.
 */

import { z } from 'zod'
import { coreGet } from './client'

export const PROPOSED_ENABLED = import.meta.env.VITE_ENABLE_PROPOSED === 'true'

// ─── Zod schemas for proposed endpoints ──────────────────────────────────────

export const ConditionSchema = z.object({
  condition_id: z.string(),
  S: z.number(), // spindle speed
  F: z.number(), // feed rate
  D: z.number(), // depth of cut
  recording_count: z.number(),
  canonical_count: z.number(),
})
export type Condition = z.infer<typeof ConditionSchema>

export const FindingSchema = z.object({
  label: z.string(),
  finding_id: z.string(),
  model_version: z.string(),
  source_path: z.string(),
  channel: z.string(),
  window_id: z.string(),
  sample_range: z.object({ sample_start: z.number(), sample_end: z.number() }),
  time_range: z
    .object({ time_start: z.number(), time_end: z.number() })
    .nullable()
    .optional(),
  score: z.number().optional(),
})
export type Finding = z.infer<typeof FindingSchema>

export const WaveformSchema = z.object({
  window_id: z.string(),
  channel: z.string(),
  samples: z.array(z.number()),
  sample_rate: z.number().optional(),
  sample_start: z.number(),
})
export type Waveform = z.infer<typeof WaveformSchema>

export const ToolWearEvaluationSchema = z.object({
  mae: z.number(),
  rmse: z.number(),
  r2: z.number(),
  model_path: z.string().optional(),
  evaluated_at: z.string().optional(),
})
export type ToolWearEvaluation = z.infer<typeof ToolWearEvaluationSchema>

// ─── API functions (only call when PROPOSED_ENABLED) ─────────────────────────

export async function getConditions(): Promise<Condition[]> {
  const raw = await coreGet<unknown[]>('/conditions')
  return z.array(ConditionSchema).parse(raw)
}

export async function getFindings(params: {
  condition_id?: string
  channel?: string
  limit?: number
}): Promise<Finding[]> {
  const qs = new URLSearchParams()
  if (params.condition_id) qs.set('condition_id', params.condition_id)
  if (params.channel) qs.set('channel', params.channel)
  if (params.limit) qs.set('limit', String(params.limit))
  const raw = await coreGet<unknown[]>(`/findings?${qs}`)
  return z.array(FindingSchema).parse(raw)
}

export async function getWindowSignal(recordingId: string, windowId: string): Promise<Waveform> {
  const raw = await coreGet<unknown>(`/recordings/${recordingId}/windows/${windowId}/signal`)
  return WaveformSchema.parse(raw)
}

export async function getToolWearEvaluation(): Promise<ToolWearEvaluation> {
  const raw = await coreGet<unknown>('/tool-wear/evaluation')
  return ToolWearEvaluationSchema.parse(raw)
}
