# DAQ Institutional Memory — Implementation Progress

## Step 1 — Manifest inventory

**Status:** Complete in code; live dataset-count verification pending dataset access.

**What:** Added `ingestion/manifest.py`, which emits a flat list containing
`source_path`, `condition_id`, `S`, `F`, `D`, and `recording_number` for every
`Recording <number>.csv` located under a condition folder.

**How:** The manifest compiles `recording_folder_pattern` directly from the
provided `domain.yaml` at discovery time and uses its named groups for every
condition value. It walks the supplied dataset root each invocation, rather
than relying on a fixed folder or file count. Focused tests cover multi-folder
runtime discovery, config validation, and a live-data count assertion driven by
`DAQ_DATASET_ROOT` (with `DAQ_EXPECTED_FILE_COUNT`, defaulting to 822).

**Why:** The manifest is the provenance skeleton for downstream DAQ processing.
Keeping it independent of CSV parsing prevents schema or signal-quality
assumptions from entering the inventory stage.

**Verification:** Synthetic manifest tests are runnable locally. The repository
does not currently contain the DAQ dataset, so its live count cannot yet be
observed or asserted in this checkout. Run:

```bash
DAQ_DATASET_ROOT=/path/to/dataset python3 -m pytest -q tests/test_manifest.py
```

## Step 2 — CSV quality gate

**Status:** Complete in code; real-file regression paths pending dataset access.

**What:** Added composable raw-byte, NUL sanitization, decoding, CSV parsing,
header, column-count, and numeric-sample checks in `ingestion/quality.py`.
Added `ingestion/parsers/csv_daq_parser.py`, whose `profile_file()` returns a
`Recording` as either canonical or quarantined and writes JSONL rejection
events. Added the missing `Recording` data-contract model exactly as specified.

**How:** Raw bytes are checksummed before NUL cleanup; cleanup happens before
`surrogateescape` decoding; and `csv.field_size_limit(1_048_576)` is raised at
module import before CSV parsing. A wrong/missing seven-field numeric header is
explicitly quarantined as `no_valid_header_numeric_match`; it is never assigned
canonical channel names. Every rejection exits before any downstream work.

**Why:** This gate prevents invalid source data from being reshaped into signals
that were never measured and therefore from contaminating windows, features,
baselines, and findings.

**Verification:** `tests/test_quality.py` covers independent helpers, a
140,000-character field (parsed after raising the CSV limit), no-header
seven-numeric input, five 2/3/4/6-column cases, malformed CSV, raw-byte read
failure, and NUL-byte audit logging. The real exception files are not present
in this checkout; their remaining concrete relative paths and expected reasons
must be supplied or made available to bind the integration regression tests to
those exact files. The live hook accepts `DAQ_DATASET_ROOT` and
`DAQ_EXCEPTION_EXPECTATIONS_JSON` (a JSON relative-path-to-reason-list map) and
asserts every configured file is quarantined for exactly its expected reason.

## Step 3 — DAQ pipeline orchestration

**Status:** Complete through the windowing handoff boundary.

**What:** Added `ingest_daq_dataset()` to orchestrate manifest discovery,
per-file profiling, full numeric loading for canonical recordings only, and an
explicit canonical-only windowing handoff. The returned `DAQIngestionRun`
contains both the records and a first-class summary with discovered, canonical,
quarantined, and per-reason totals.

**How:** The pipeline starts with `discover_manifest()`, passes the manifest
condition ID into `profile_file()`, and never calls the numeric loader or
windowing handler for an initial quality rejection. Full numeric conversion
validates all rows (including those beyond the Step 2 sample); a late failure is
quarantined, JSONL-logged, and counted before it can be handed off.

**Why:** The run summary is the durable evidence trail for later claims about
which recordings were eligible for signal analysis. The injectable handler
keeps this step limited to orchestration because `signal/windowing.py` has not
yet been implemented.

**Verification:** `tests/test_daq_pipeline.py` verifies the exact summary
shape, canonical-only numeric handoff, and a non-numeric value after the
profile sample being quarantined before handoff.

## Step 4 — Signal preprocessing and windowing

**Status:** Complete.

**What:** Added per-channel NaN interpolation, Time-delta sampling-rate
calculation, optional data-confirmed resampling, and fixed-length
channel-specific `SignalWindow` generation.

**How:** Sampling rate is the inverse median of actual, finite, strictly
positive Time deltas. A configured resampling rate is rejected unless it
matches that measured rate within tolerance. NaNs are interpolated separately
within each measurement channel while preserving sample indices. Windows use
2048 samples and 50% overlap by default; their end index is exclusive. Time
citations are populated only when Time semantics can be confirmed.

**Why:** Signal windows are the evidence objects used by later features and
findings. Preserving channel identity, sample range, and validated time range
keeps that evidence traceable without guessing sampling frequency.

**Verification:** `tests/test_signal.py` covers measured 10 Hz sampling, NaN
handling, rejection of an unconfirmed configured rate, six-channel fixed
windows with time citations, and invalid-Time windows without time citations.

## Step 5 — Per-window signal features

**Status:** Complete.

**What:** Added standard per-channel/per-window time-domain features (mean,
standard deviation, RMS, peak, crest factor, excess kurtosis, skewness) and
frequency-domain band energy plus spectral centroid.

**How:** `extract_window_features()` always computes time-domain values and
only enables FFT features when its caller supplies a valid sampling rate. Every
frequency helper rejects missing or invalid `fs`. Default low/mid/high bands
partition the *measured* Nyquist frequency; callers may inject configured band
edges without changing feature logic. The named values and their stable ordered
vector are attached to the corresponding `SignalWindow`.

**Why:** This preserves the central rule that the LLM never performs signal
math and that frequency evidence cannot be created from an assumed rate.

**Verification:** `tests/test_features.py` confirms time-only extraction,
missing-fs blocking, a 5 Hz FFT diagnostic under an explicitly supplied 100 Hz
rate, and standard time-domain values.

## Step 6 — Per-condition baselines

**Status:** Complete.

**What:** Added canonical-only normal feature profiles keyed by
`(condition_id, channel)`. Each profile records feature-wise mean and
population standard deviation, the contributing recording IDs, and window
count.

**How:** `build_per_condition_baselines()` joins every window to its source
`Recording`, discards quarantined recordings before aggregation, and rejects
unknown, non-finite, or differently shaped feature vectors. Profiles are
separate for each condition/channel pair; no global baseline is calculated.

**Why:** Changing S/F/D legitimately changes vibration, load, and current
behavior. A condition-specific normal profile prevents those expected process
differences from being mislabeled as anomalies.

**Verification:** `tests/test_baselines.py` confirms separated condition and
channel profiles, expected mean/std values, and exclusion of a quarantined
recording.

## Step 7 — Unsupervised anomaly detection

**Status:** Complete.

**What:** Added a first-pass diagonal Mahalanobis detector scoped to each
condition/channel baseline. It emits typed `Finding` objects only for windows
whose unsupervised distance exceeds the chosen threshold.

**How:** The detector uses Step 6's mean and standard-deviation vectors as a
diagonal covariance approximation—no fault labels or global baseline are used.
Every finding includes the source CSV path, recording and window IDs, channel,
sample/time range, condition, baseline provenance, and threshold. Quarantined
recordings are never scored.

**Why:** The score explains a deviation from normal behavior for the same
S/F/D setting, while the evidence lets any later response trace precisely back
to the raw signal segment.

**Verification:** `tests/test_anomaly.py` covers standardized distance,
complete evidence provenance, thresholding, and exclusion of a quarantined
recording.

## Step 8 — Leakage-safe evaluation splits

**Status:** Complete.

**What:** Added train/test splitting by complete condition when two or more
canonical conditions are present, with a complete-recording fallback otherwise.

**How:** `split_recordings()` excludes quarantined records, deterministically
partitions condition IDs first, and includes every recording under a held-out
condition on the same split side. The fallback shuffles recording IDs, never
windows. `partition_windows_by_recording()` only assigns windows according to
that prior recording split and rejects unknown IDs. Every split asserts zero
recording-ID overlap.

**Why:** Adjacent DAQ windows are correlated. Window-level splits would leak
the same recording's behavior into both training and testing, inflating anomaly
performance claims.

**Verification:** `tests/test_evaluation.py` verifies whole-condition holdout,
whole-recording fallback, zero window-recording overlap, and invalid small
split rejection.

## Step 9 — DAQ provenance graph and ontology

**Status:** Complete.

**What:** Added a typed DAQ ontology and upgraded the Neo4j-style in-memory
simulation driver to return typed `GraphEdge` objects from `get_neighbors()`.
The populated lineage is `Condition -[:CAPTURED_UNDER]-> Recording
-[:HAS_WINDOW]-> SignalWindow -[:EXHIBITS_PATTERN]-> Finding`.

**How:** The ontology creates namespaced node IDs, validates every referenced
condition, recording, and window before linking, and uses idempotent `MERGE`
semantics in the driver. `SIMILAR_TO` is supported with a similarity property
but only populated by a later feature-similarity step.

**Why:** The graph preserves the full provenance path from experimental setting
to an analytical finding, so findings remain inspectable rather than becoming
untraceable scores.

**Verification:** `tests/test_ontology.py` checks typed neighbor edges for the
complete lineage and verifies the reserved `SIMILAR_TO` edge shape.

## Step 10 — DAQ retrieval

**Status:** Complete.

**What:** Added exact DAQ metadata lookup, numeric feature-vector similarity,
and provenance-graph retrieval fusion.

**How:** `MetadataIndex` joins windows to recordings and conditions, then
matches only exact `condition_id`, S, F, D, recording ID, and channel filters;
quarantined recordings never match. `FeatureStore` provides insert plus cosine
or Euclidean similarity search over finite feature vectors. `DAQRetriever`
strictly orders its flow: metadata candidates first, feature ranking second,
then typed neighbors for both the matched Recording and SignalWindow nodes.

**Why:** DAQ evidence is numerical and structured, not textual. This preserves
the old retrieval-fusion intent without treating signal windows as text chunks.

**Verification:** `tests/test_daq_retrieval.py` confirms filter-first ranking,
exclusion of quarantined input, numeric nearest-window ordering, and typed
`HAS_WINDOW` graph context.

## Step 11 — Evidence-only LLM explanation

**Status:** Complete.

**What:** Added a DAQ-specific prompt builder and explanation orchestrator that
accept computed Findings, their evidence, condition metadata, and typed graph
context—not raw signal arrays.

**How:** `DAQExplanationOrchestrator` validates every Finding has recording ID,
CSV path, channel, window ID, and sample range before it can call an LLM. The
prompt and system instruction explicitly prohibit calculating, estimating,
deriving, or inventing numerical results. Citations are returned directly from
the already-validated Finding evidence rather than inferred from LLM text.

**Why:** The LLM's role is natural-language explanation of analytics evidence;
it must never become an untraceable signal-math engine or fabricate a number.

**Verification:** `tests/test_daq_orchestrator.py` verifies the no-computation
instruction, absence of raw signals, path/channel/range citations, graph
context, and prevention of an LLM call for incomplete evidence.

## Step 12 — DAQ API endpoints

**Status:** Complete.

**What:** Added DAQ folder ingestion, run profiling, scoped analysis, and
evidence-only query paths to the API while retaining legacy document endpoints.

**How:** `POST /ingest` accepts JSON with a dataset folder and config path,
runs the manifest plus quality pipeline, and stores a first-class summary for
`GET /profile`. `POST /analyse` selects only canonical recordings, creates
windows, extracts features, builds per-condition baselines, detects
unsupervised anomalies, and refreshes the feature/metadata/graph stores.
`POST /query` uses the numeric retrieval path when given a DAQ `question`, then
passes only matching Findings into the evidence-only explanation orchestrator.
`GET/PUT /config` retain the existing save-and-hot-reload behavior.

**Why:** The API exposes the full DAQ evidence chain programmatically while
preserving quality counts and provenance at every handoff. It never sends raw
signal arrays to the LLM.

**Verification:** `tests/test_daq_api.py` exercises folder ingest, exact
profile summary, analysis, and evidence-cited DAQ query end to end.

## Blueprint completion audit — 2026-09-18

The twelve implementation steps are complete in code and the synthetic
regression suite covers every specified behavior. The following checklist
separates verified implementation from claims that require the actual DAQ data
to be mounted in this checkout.

- [ ] **Live manifest count:** pending `DAQ_DATASET_ROOT`; the manifest is
  runtime-discovered and its live test asserts the current count (default 822),
  but no CSV corpus is present here.
- [ ] **Exact real-file quarantine regression:** pending the dataset and the
  concrete paths/reasons for all exception files. Synthetic tests cover the
  no-header 7-column case, five 2/3/4/6-column cases, raw-byte failure,
  malformed CSV, and NUL bytes.
- [ ] **`Recording 15.csv` verified specifically:** pending the real file. The
  1,048,576 field-size limit is verified with a 140,000-character CSV field;
  whether the actual file is canonical or quarantined depends on its contents
  after it can be read and must not be guessed.
- [x] **NUL sanitization:** raw-byte cleanup occurs before surrogateescape
  decoding and emits `null_bytes_removed`; verified by unit test.
- [x] **Measured fs / feature gating:** fs comes from Time deltas; frequency
  features reject absent/invalid fs; verified by unit test.
- [x] **Canonical-only time features, condition baselines, and unsupervised
  Mahalanobis anomalies:** implemented and verified by unit tests.
- [x] **Leakage-safe evaluation:** whole-condition preferred and whole-recording
  fallback have zero recording-ID overlap; verified by unit tests.
- [x] **Typed provenance graph, metadata + feature retrieval, and evidence-only
  explanation:** implemented and verified by unit tests.
- [ ] **`/profile` matches a manual live profile:** endpoint behavior is tested
  end-to-end with a fixture dataset; exact live-count parity awaits the DAQ
  corpus.

**Next live verification command:**

```bash
DAQ_DATASET_ROOT=/path/to/daq-data \
DAQ_EXPECTED_FILE_COUNT=822 \
python3 -m pytest -q tests/test_manifest.py tests/test_quality.py
```

Provide `DAQ_EXCEPTION_EXPECTATIONS_JSON` as a JSON map of exact relative paths
to expected reason lists to activate the real-file quarantine assertions.

## Step 13 — Real DAQ corpus and supervised tool-wear model

**Status:** In progress — real data schema verified; full-corpus train/evaluate running next.

**What:** The supplied `Readngs_DAQ_Data` corpus contains 25 discovered
conditions and exactly 822 recordings (about 41 GB). The supplied
`Tool_Wear_Value_Table.xlsx` has 25 case columns keyed by condition ID and run
number, with 824 numeric labels (labels beyond an available recording are
ignored). Added a recording-level supervised tool-wear regressor whose inputs
are computed DAQ diagnostics plus S/F/D—not spreadsheet text.

**How:** The parser now recognizes only the dataset's exact
`Unit,V,V,V,V,V,V` second row as explicit export metadata, skips it during
numeric validation/loading, and still rejects all other invalid headers/rows.
`analytics/tool_wear.py` joins a label only by `(condition_id, Recording N)`,
derives rate-independent per-channel features from evenly distributed signal
samples, and trains a HistGradientBoostingRegressor with whole-recording
train/test separation. `train_tool_wear_model.py` writes a local model and an
evaluation JSON report under ignored `artifacts/tool_wear/`.

**Why:** The workbook gives a supervised target (tool wear in µm); it does not
replace DAQ signal evidence. Matching on the explicit condition/run keys makes
the target linkage auditable and prevents hidden label inference.

## API path correction — 2026-09-23

**Status:** Complete.

**Root cause:** The DAQ corpus was moved under `dataset/Readngs_DAQ_Data`, but
the API request used the old root-relative `Readngs_DAQ_Data` path. The old
handler converted that client path mistake into a generic 500 response.

**Fix:** `POST /ingest` now resolves an explicit directory, the project-relative
directory, or the project-local `dataset/<name>` mount. Invalid dataset/config
paths return HTTP 400 with the exact expected path. API tests cover this error
case.

## API responsiveness correction — 2026-09-23

**Root cause:** Synchronous ingestion read the entire 41 GB corpus and then
re-read every canonical file for full numeric loading. While that request was
running, the single API worker could not answer `/profile`, which looked like
the API returned nothing.

**Fix:** JSON `POST /ingest` now starts a background, profile-only pass and
returns HTTP 202 immediately. `GET /profile` reports `running`, `complete`, or
an explicit failure. Full numeric loading remains mandatory for `POST /analyse`
and therefore happens only for the requested condition/recording. Add
`"wait": true` only for small fixture data or a terminal job where a blocking
response is desired.

## API analysis responsiveness correction — 2026-09-23

**Root cause:** Condition-level windowing and feature extraction can involve
many large recordings and thousands of windows. The synchronous `/analyse`
request left Curl waiting with no response even though the server was working.

**Fix:** `POST /analyse` now returns HTTP 202 immediately and performs the
work in a background job. Poll `GET /analyse/status` for `running`, `complete`,
or an explicit error. Use `"wait": true` only for small test requests.

## Explanation response-size correction — 2026-09-23

**Root cause:** A cited recording's graph neighborhood includes every one of
its `HAS_WINDOW` edges. Returning that whole neighborhood in a query response
produced a very large JSON dump rather than a concise explanation.

**Fix:** The LLM explanation path now includes only the recording's
`CAPTURED_UNDER` condition lineage and the cited window's exact `HAS_WINDOW`,
`EXHIBITS_PATTERN`, and optional `SIMILAR_TO` edges. This preserves provenance
while keeping a chatbot response bounded and useful.

## Persistent DAQ ingest and analysis cache — 2026-09-23

**Why:** The 822-recording corpus is expensive to profile and analyse. The
per-condition baseline is the fitted reference used by the unsupervised
Mahalanobis detector, so users should not need to rebuild it merely because the
API server restarts.

**What:** `POST /ingest` now fingerprints the discovered manifest (absolute
paths, file byte sizes, modification times, and config content) and persists
the profile result under `runtime/daq_cache/`. A matching later ingest restores
the canonical/quarantined `Recording` inventory without re-reading all CSV
contents. `POST /analyse` persists the computed windows, feature vectors,
per-condition baselines, and traceable `Finding` objects keyed by dataset
fingerprint and analysis settings. On a matching request it restores those
facts and rebuilds the in-memory feature index and provenance graph, without
re-windowing or re-training the baseline.

**Control:** Send `"force": true` in either request to deliberately bypass
the relevant cache after a source change. Cache files are derived local runtime
artefacts and are excluded from Git.

## Real LLM provider configuration — 2026-09-23

**Root cause:** `llm/orchestrator.py` instantiated `MockLLM` unconditionally.
Its response was a test placeholder containing only the prompt size, even when
the DAQ retrieval, evidence, and prompt were correct.

**Fix:** Added the configurable `OpenAIResponsesLLM` provider. Set
`LLM_PROVIDER=openai`, `OPENAI_API_KEY`, and optionally `OPENAI_MODEL` before
starting Uvicorn. The API calls the provider through the Responses API using
the evidence-only prompt and system instruction. In mock mode, DAQ `/query`
now returns a clear HTTP 503 configuration error rather than a fabricated
answer. `.env.example` documents the setup and `.env` remains ignored.

## Gemini transient-capacity handling — 2026-09-24

**Root cause:** Gemini returned HTTP 503 `UNAVAILABLE`, explicitly reporting
temporary high demand for the selected model. Provider discovery and the API
key were already successful, as confirmed by `GeminiLLM` loading.

**Fix:** Gemini generation retries only temporary 429/5xx provider responses
with short exponential backoff (three attempts by default). It never falls
back to a mock response. If all attempts fail, `/query` reports HTTP 503 with a
clear retry/model-selection message. `GEMINI_MAX_RETRIES` controls the retry
count.

## Gemini model selection — 2026-09-24

**What:** Queried the Gemini model catalogue available to the configured key.
The previous 3.x Flash provider returned repeated temporary 503 high-demand
errors. `gemini-2.5-flash` then returned a provider migration message that it
is unavailable to new users and explicitly recommended `gemini-3.6-flash`.
The local ignored `.env` therefore selects `gemini-3.6-flash` for evidence-only
DAQ chatbot explanations.

## Concise answers and faster scoped analysis — 2026-09-24

**Root cause:** `/query` exposed internal prompt, full Finding objects,
baseline recording lists, and graph edges. It also ignored the DAQ `top_k`
field because the request schema did not retain it. Analysis repeated NaN
preprocessing for every window and always processed all six non-Time channels.

**Fix:** Public query responses now include only `answer`, a compact citation
list, and `finding_count`; internal prompt/graph/debug material stays private.
The prompt has compact citations and asks for a short summary with at most
three representative windows. `top_k` is honoured. `POST /analyse` accepts an
optional `channels` list, and preprocessing now runs once per selected channel
rather than once per window. Example: `"channels":["Vib_Spindle"]` avoids
analysing the other five channels for a spindle-only question.

## Evidence-content explanations — 2026-09-24

**Root cause:** An anomaly Finding contained a traceable location and a single
Mahalanobis score, but no analytics-produced indication of which extracted
features departed most from the same-condition baseline. The LLM could only
repeat recordings, ranges, and scores.

**Fix:** The detector now records the three largest computed per-feature
standardized departures (window value and baseline mean) in Finding evidence.
The prompt supplies these already-computed facts so the chatbot can explain
what changed, while still never performing signal math. Conversational answers
cite finding IDs rather than repeating raw CSV paths; compact structured
citations retain the required provenance. The detector version was increased
to `mahalanobis-diagonal-v2`, automatically invalidating old analysis cache.

## Natural-language answer formatting — 2026-09-24

**Root cause:** The LLM prompt included raw feature and baseline values, so the
otherwise valid answer resembled a CSV/JSON diagnostics export rather than a
readable explanation.

**Fix:** Analytics now produces a plain-language statement for each dominant
feature departure (for example, low-frequency vibration energy relative to the
condition baseline). The prompt exposes only these computed statements, short
labels such as `[Finding 1]`, and concise range metadata. Raw floats, SHA IDs,
and file paths are omitted from answer prose; the separate compact citations
retain provenance for audit. Version `mahalanobis-diagonal-v3` forces new
cached findings with this evidence.

## Frontend automatic chat server — 2026-09-24

**What:** Added `server.py`, a frontend-facing FastAPI entrypoint. `POST /chat`
deterministically extracts an explicit `condition N` and one canonical signal
from the user's question, restores exact cached analytics where available, or
starts the appropriate condition/channel analysis automatically. It then sends
only computed findings to the existing evidence-only explanation pipeline.

**Why:** Frontend users should ask questions naturally rather than manually
calling `/ingest` and `/analyse`. New evidence cannot be truthfully answered in
seconds before signal analytics finishes, so `/chat` returns HTTP 202 while a
new scope is being prepared; `GET /chat/status` lets the frontend poll and
resend the question. Subsequent matching cached scopes answer immediately.
