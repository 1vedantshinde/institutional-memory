# Backend Requests

These endpoints are proposed but not yet implemented. They are used by the **Waveforms & Findings** and **Tool Wear** preview pages (visible when `VITE_ENABLE_PROPOSED=true`), which run exclusively against MSW mocks.

See `src/api/proposed.ts` for the TypeScript types and `src/mocks/handlers.ts` for the MSW mock implementations.

---

## GET /conditions

List all 25 process conditions with their (S, F, D) parameters and recording counts.

**Response** `200 OK`
```json
[
  {
    "condition_id": "4",
    "S": 900,
    "F": 0.11,
    "D": 0.6,
    "recording_count": 33,
    "canonical_count": 32
  }
]
```

**Notes**
- `S` = spindle speed (RPM), `F` = feed rate (mm/rev), `D` = depth of cut (mm)
- `canonical_count` ≤ `recording_count`

---

## GET /findings

Query the indexed findings across all analysed conditions.

**Query parameters**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `condition_id` | string | no | Filter by condition |
| `channel` | string | no | Filter by channel name |
| `limit` | int | no | Max results (default 50) |

**Response** `200 OK`
```json
[
  {
    "label": "Finding 1",
    "finding_id": "finding-0298a0f1",
    "model_version": "mahalanobis-diagonal-v3",
    "source_path": "dataset/Readngs_DAQ_Data/N_4/Recording 12.csv",
    "channel": "Vib_Spindle",
    "window_id": "win-12-004",
    "sample_range": { "sample_start": 4096, "sample_end": 6144 },
    "time_range": { "time_start": 0.4096, "time_end": 0.6144 },
    "score": 5.8
  }
]
```

**Notes**
- Same schema as individual citations in `/chat` and `/query` responses, plus an optional `score` field (Mahalanobis distance)

---

## GET /recordings/{id}/windows/{window_id}/signal

Return downsampled signal samples for a specific analysis window, suitable for a waveform preview.

**Path parameters**
| Name | Description |
|------|-------------|
| `id` | Recording identifier (numeric or string) |
| `window_id` | Window identifier, e.g. `win-12-004` |

**Response** `200 OK`
```json
{
  "window_id": "win-12-004",
  "channel": "Vib_Spindle",
  "samples": [0.12, 0.15, …],
  "sample_rate": 10000,
  "sample_start": 4096
}
```

**Notes**
- `samples` length = `sample_end - sample_start` (2048 for the default window size). Downsampling is optional for preview — the frontend renders whatever length is returned.
- `sample_rate` (Hz) is optional but enables time-axis labels.

---

## GET /tool-wear/evaluation

Return the evaluation metrics from the offline tool-wear model (produced by the CLI training script as `evaluation.json`).

**Response** `200 OK`
```json
{
  "mae": 0.031,
  "rmse": 0.047,
  "r2": 0.924,
  "model_path": "models/tool_wear/model.joblib",
  "evaluated_at": "2026-09-28T10:00:00Z"
}
```

**Notes**
- `model_path` and `evaluated_at` are optional metadata fields.
- The endpoint simply reads and returns `evaluation.json`; it does not re-run evaluation.
