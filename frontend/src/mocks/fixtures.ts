import type { ChatReadyResponse, ChatAnalysingResponse, ChatStatusResponse, RawProfile, RawAnalysisStatus } from '../api/schemas'

export const MOCK_CHAT_INGESTING: ChatAnalysingResponse = {
  status: 'ingesting',
  message: 'Preparing the DAQ inventory. Retry shortly.',
}

export const MOCK_CHAT_ANALYSING: ChatAnalysingResponse = {
  status: 'analysing',
  condition_id: '4',
  channel: 'Vib_Spindle',
  message: 'Analysing the requested signal. Retry this question when status is analysis_ready.',
  status_url: '/chat/status',
}

export const MOCK_CHAT_READY: ChatReadyResponse = {
  // Same Markdown shape the real backend's LLM answers use
  answer: [
    '### Practical Summary',
    'For condition 4, spindle vibration showed elevated low-frequency energy compared to the condition baseline.',
    '',
    '### Representative Findings',
    '* **[Finding 1]**: Low-frequency vibration energy and overall vibration level (RMS) were about 3 standard deviations above the condition baseline.',
    '* **[Finding 2]**: A later window showed the same pattern; no matching anomaly appeared on the table vibration channel.',
  ].join('\n'),
  citations: [
    {
      label: 'Finding 1',
      finding_id: 'finding-0298a0f1',
      model_version: 'mahalanobis-diagonal-v3',
      source_path: 'dataset/Readngs_DAQ_Data/N_4/Recording 12.csv',
      channel: 'Vib_Spindle',
      window_id: 'win-12-004',
      sample_range: { sample_start: 4096, sample_end: 6144 },
      time_range: { time_start: 0.4096, time_end: 0.6144 },
    },
    {
      label: 'Finding 2',
      finding_id: 'finding-7c1d02aa',
      model_version: 'mahalanobis-diagonal-v3',
      source_path: 'dataset/Readngs_DAQ_Data/N_4/Recording 12.csv',
      channel: 'Vib_Spindle',
      window_id: 'win-12-007',
      sample_range: { sample_start: 7168, sample_end: 9216 },
      time_range: null, // intentionally null to exercise missing-time rendering
    },
  ],
  finding_count: 2,
}

export const MOCK_CHAT_STATUS_ANALYSING: ChatStatusResponse = { status: 'analysing' }
export const MOCK_CHAT_STATUS_READY: ChatStatusResponse = { status: 'analysis_ready' }

export const MOCK_PROFILE_RUNNING: RawProfile = { status: 'running' }

export const MOCK_PROFILE_COMPLETE: RawProfile = {
  status: 'complete',
  summary: {
    discovered: 822,
    canonical: 815,
    quarantined: 7,
    by_reason: {
      'column_count_mismatch:4': 2,
      'column_count_mismatch:3': 1,
      'no_valid_header_numeric_match': 1,
      'unparseable_csv': 1,
      'column_count_mismatch:6': 1,
      'column_count_mismatch:2': 1,
    },
  },
}

export const MOCK_ANALYSIS_STATUS_RUNNING: RawAnalysisStatus = { status: 'running' }
export const MOCK_ANALYSIS_STATUS_COMPLETE: RawAnalysisStatus = {
  status: 'complete',
  model_version: 'mahalanobis-diagonal-v3',
  message: 'Analysis complete. 12 anomalous windows detected across 2 recordings.',
}

export const MOCK_CONFIG = {
  dataset_path: 'dataset/Readngs_DAQ_Data',
  config_path: 'config/domain.yaml',
  channels: ['Time', 'Vib_Spindle', 'Vib_Table', 'X_Load_Cell', 'Y_Load_Cell', 'Z_Load_Cell', 'Current'],
  anomaly_model: 'mahalanobis-diagonal-v3',
  window_size_samples: 2048,
  overlap: 0.5,
  anomaly_threshold: 3.0,
  conditions: { count: 25, parameter: 'N' },
  quality_gate: {
    required_columns: 7,
    allow_null_byte_sanitization: true,
  },
}

// Proposed endpoint fixtures (used only when VITE_ENABLE_PROPOSED=true)
export const MOCK_CONDITIONS = Array.from({ length: 25 }, (_, i) => ({
  condition_id: String(i + 1),
  S: 500 + i * 100,
  F: 0.05 + i * 0.02,
  D: 0.5 + (i % 5) * 0.1,
  recording_count: 30 + (i % 5),
  canonical_count: 28 + (i % 5),
}))

export const MOCK_FINDINGS = [
  {
    label: 'Finding 1',
    finding_id: 'finding-0298a0f1',
    model_version: 'mahalanobis-diagonal-v3',
    source_path: 'dataset/Readngs_DAQ_Data/N_4/Recording 12.csv',
    channel: 'Vib_Spindle',
    window_id: 'win-12-004',
    sample_range: { sample_start: 4096, sample_end: 6144 },
    time_range: { time_start: 0.4096, time_end: 0.6144 },
    score: 5.8,
  },
]

export const MOCK_TOOL_WEAR = {
  mae: 0.031,
  rmse: 0.047,
  r2: 0.924,
  model_path: 'models/tool_wear/model.joblib',
  evaluated_at: '2026-09-28T10:00:00Z',
}
