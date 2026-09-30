import { coreGet, corePost, corePut, LLM_ANSWER_TIMEOUT_MS } from './client'
import {
  RawProfileSchema,
  RawAnalysisStatusSchema,
  ConfigResponseSchema,
  QueryResponseSchema,
  type RawProfile,
  type RawAnalysisStatus,
  type ConfigResponse,
  type ChatReadyResponse,
} from './schemas'

export async function postIngest(params: {
  folder_path: string
  config_path: string
  force?: boolean
  wait?: boolean
}): Promise<unknown> {
  return corePost('/ingest', params)
}

export async function getProfile(): Promise<RawProfile> {
  const raw = await coreGet<unknown>('/profile')
  return RawProfileSchema.parse(raw)
}

export async function postAnalyse(params: {
  condition_id: string | number
  channels?: string[]
  window_size_samples?: number
  overlap?: number
  anomaly_threshold?: number
  force?: boolean
  wait?: boolean
}): Promise<unknown> {
  return corePost('/analyse', params)
}

export async function getAnalyseStatus(): Promise<RawAnalysisStatus> {
  const raw = await coreGet<unknown>('/analyse/status')
  return RawAnalysisStatusSchema.parse(raw)
}

export async function postQuery(params: {
  question: string
  filters: { condition_id?: string; channel?: string }
  top_k?: number
}): Promise<ChatReadyResponse> {
  const raw = await corePost<unknown>('/query', params, { timeoutMs: LLM_ANSWER_TIMEOUT_MS })
  return QueryResponseSchema.parse(raw)
}

export async function getConfig(): Promise<ConfigResponse> {
  const raw = await coreGet<unknown>('/config')
  return ConfigResponseSchema.parse(raw)
}

export async function putConfig(config: Record<string, unknown>): Promise<unknown> {
  return corePut('/config', config)
}
