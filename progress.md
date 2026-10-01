# DAQ Institutional Memory — Implementation Progress

This is the project's build log. The overview below says where things stand
today. The dated entries after it record, in order, what was built or fixed,
how, why, and how it was verified. For what the system is and how to run it,
start with the [README](README.md).

## Project status at a glance — 2026-10-01 (`vaishnavi` branch)

**Overall:** Working end to end on the real corpus. A question about a
specific run (one condition and signal) is answered from deterministically
computed findings, and every claim links to its source window. A general
question about the project, machine or vocabulary is answered from the
knowledge documents in `knowledge_docs/pdfs/`, citing the passages used.

This branch is `main` merged into `vaishnavi` (document-RAG infrastructure),
plus the Tier-1 knowledge documents (see the 2026-10-01 entries).

| Area | State | Notes |
|---|---|---|
| Dataset discovery and quality gate | ✅ Done | 822 recordings / 25 conditions discovered on the real corpus. Last full profile: 805 canonical, 17 quarantined (all column-count mismatches). |
| Signal processing, features, baselines | ✅ Done | Measured sampling rate; 2,048-sample windows, 50% overlap; per-(condition, channel) baselines from canonical recordings only. |
| Anomaly detection | ✅ Done | `mahalanobis-diagonal-v3`; findings carry plain-language feature departures and full provenance. |
| Provenance graph and retrieval | ✅ Done | Graph build made linear (was quadratic) on 2026-09-29. |
| Evidence-only explanations | ✅ Done | Gemini primary with configurable fallback models; answers cite `[Finding N]`. |
| Chat server (`server.py`) | ✅ Done | Automatic ingest/analysis, reuse of any covering cached analysis, warm start. |
| Web app (`frontend/`) | ✅ Done | Ask, Dataset Health, Analysis, Evidence, Config, About; mock mode; automated tests. |
| Tool-wear regression | 🟡 Trained, not served | 161 held-out recordings: MAE 14.3 µm, RMSE 18.9 µm, R² 0.93. Not yet exposed via API/UI. |
| Knowledge documents (Tier-1 PDFs) | ✅ Done | 4 PDFs indexed at startup (8–12 chunks each); 18 glossary terms in `domain.yaml`; `Document -[:DOCUMENTS]-> Concept` edges; general questions answered from them with `[Source N]` passages. |
| Document-RAG infrastructure (from `vaishnavi`) | 🟡 Available, mostly optional | Query router, keyword retrieval, pypdf parser, API-key auth used now. Qdrant/Neo4j/Anthropic/neural embeddings work only when configured; eval harness needs real golden answers. |
| Mixed answers (findings + documents) | ⏳ Not started | A question is answered from one source or the other. |
| Waveform viewer, findings list | ⏳ Not started | Needs new backend endpoints (`frontend/BACKEND_REQUESTS.md`); UI previews exist on mock data only. |

**Test status (2026-10-01):** backend 82 passed / 2 skipped (skips need the
live dataset); frontend 50 passed; type check clean.

**Known issues / open items**

1. Feature statements say "vibration" for every channel, including load cells
   and motor current. The numbers are correct; the wording needs to be
   channel-aware.
2. Run-specific questions must name exactly one condition and one signal;
   comparisons aren't supported, and answers don't yet mix findings with
   document passages.
3. Backend is reachable from the same machine only (no LAN access yet).
4. Tool-wear evaluation splits by whole recording, not whole condition; a
   condition-held-out evaluation would be stricter.
5. The configured Gemini model is often overloaded; fallback models are
   configured in `.env`.
6. Live-data regression checks for specific quarantined files still need the
   expected file/reason list (see the Step 1–12 audit below).
7. Document search is keyword-only by default (the default embedder isn't
   semantic), and PDF tables come out as flat text, so exact table-row lookups
   (e.g. one condition's recording count) depend on the row's words.
8. `test_api.py` (root) sends `PUT /config`, which rewrites
   `config/domain.yaml` and drops its comments. Don't run it against a config
   you want to keep as-is.

**How to run and verify:** see README §5 (run) and §9 (tests).

---

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

**Status:** Trained and evaluated on the full corpus (see result below); not
yet served through the API or web app.

**Result:** 804 labelled canonical recordings, 46 features, whole-recording
split of 643 train / 161 test. Test MAE 14.3 µm, RMSE 18.9 µm, R² 0.93
(`artifacts/tool_wear/evaluation.json`, git-ignored). Held-out recordings can
share a condition with training recordings; a whole-condition hold-out is the
stricter follow-up evaluation.

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

## Frontend stabilisation — 2026-09-29

**Status:** Complete. `npx tsc --noEmit` (0 errors, was 57), `npx vite build`
(no warnings), and `npx vitest run` (24/24 across 5 files, was 0 collected)
are all clean. Verified in headless Chrome against the MSW mocks.

**Root cause (blank app):** `src/api/schemas.ts` called `.passthrough()` on a
`z.record()`, which zod v4 does not support. The TypeError is thrown while the
ES module graph evaluates, so `main.tsx` never ran and every route rendered an
empty `#root`. Separately, `vite.config.ts` imported
`.figma/make/site.json`, a Figma Make-only file absent outside Figma, so
neither `vite` nor `vite build` could start.

**Fixes:**
- `ConfigResponseSchema` → `z.record(z.string(), z.unknown())`; every
  `z.record(z.number())` → `z.record(z.string(), z.number())` so reason-count
  maps type as `Record<string, number>`.
- `vite.config.ts`: inlined the site config (title/lang), removed the
  duplicate `proxy` block, default port 8443 → 5173 (what the README and CORS
  note assume), and `loadEnv()` so `.env.local` reaches the proxy targets/PORT.
- Tests: one setup file (`src/test/setup.ts`) now starts MSW; previously the
  wired-up file only mocked storage, so MSW never ran. Fake timers use
  `shouldAdvanceTime` (Testing Library's `waitFor` hung under Vitest fakes).
- `postChat` wraps connection failures in `NetworkError`/`TimeoutError` and
  tolerates non-JSON error bodies; before, a refused connection surfaced as
  "An unexpected error occurred." instead of "Can't reach the chat server".
  Error messages now read FastAPI's `detail`, so a 400 shows its exact path
  message rather than `HTTP 400`.
- Analysis: the job card unmounted the moment a run completed, hiding
  "Ask about this scope" (the Analysis→Ask handoff); a second run also reused
  the previous run's cached `complete` status and never polled.
- Dataset Health: the quarantine-rate KPI rendered `NaN` (string passed
  through `Number()`).
- Config: validates the payload is a JSON object, lists each top-level key as
  added/removed/changed, disables Confirm when nothing changed, and states the
  change affects parsing and analysis.
- `src/index.css`: an unlayered `* { margin: 0; padding: 0 }` outranked all
  Tailwind v4 utilities, silently disabling every `p-*`/`m-*`/`space-*` class.
  Base styles now live in `@layer base`.
- Accessibility: removed the live region wrapping the ticking elapsed timer;
  Dataset/Config completion is announced through `#live-announcer`; chat
  auto-scroll honours `prefers-reduced-motion`.
- All six main routes are lazy-loaded (single 1.03 MB chunk → 397 kB entry
  plus per-page chunks).
- Deleted the unrouted duplicate pages under `src/features/{about,analysis,
  config,dataset,evidence,proposed}`, `features/ask/{AskPage,index}`,
  `src/lib/export.ts` and `src/lib/cn.ts` (confirmed unreachable from
  `main.tsx` with the TypeScript compiler's module resolution).
- Added `frontend/.env.example`, `frontend/.gitignore`, and typed
  `ImportMetaEnv`.

**Verification:** Beyond the three commands above, a headless-Chrome audit of
all six routes at 360 px and 1280 px in both themes found no horizontal
overflow and a visible focus ring on every tab stop. With reduced motion
emulated, all animations/transitions computed to ~0 s. The mocked Ask flow
(202 → poll → auto-resend → 200 with F1/F2 citation chips) and Dataset
ingest → KPIs were exercised end to end.

## Chat answers without re-analysis — 2026-09-29

**Root cause:** Three backend issues made every question slow or failing.
(1) `knowledge/graph_store.py` deduplicated edges with `candidate not in
self.edges`, a list scan, so rebuilding the provenance graph from a cached
analysis was O(n²): 25 s for one condition/channel and ~200 s once a second
scope was loaded. (2) `/chat` only reused a cache for the exact
(condition, single channel) request, and replaced the in-memory scope on
every restore, so broader runs (e.g. all channels from the Analysis page) and
previously asked scopes were ignored. (3) The configured Gemini model
(`gemini-3.6-flash`) was returning 503 "overloaded" with no fallback.

**Fix:** Edge MERGE and neighbor lookup now use hash indexes (restore 25 s →
0.6 s; two scopes 204 s → 1.6 s). `server.py` restores from any covering
default-settings cache (condition+channel, condition, channel, whole dataset —
valid because baselines/findings are computed per (condition, channel)) and
merges it into memory, and restores the DAQ inventory at startup
(`DAQ_WARM_START=0` disables). `GeminiLLM` tries `GEMINI_FALLBACK_MODELS` in
order on transient 429/5xx/connection failures, one attempt per model with
retries reserved for the last.

**Verification:** 53 Python tests pass (new: fallback order, no fallback on
4xx, covering-cache reuse without starting analysis). Live, from a fresh
server: inventory ready in 1.6 s; questions on cached scopes answered in
10–15 s (previously 126 s / 276 s / 47 s) with no analysis run.

## Frontend ↔ real backend integration — 2026-09-29

**Root cause:** The web app had been built against mock responses, and the
real chat server behaves differently in ways the mocks didn't cover.
(1) On a fresh backend, `/chat` first replies 202 `ingesting` (no condition or
channel yet), then status `ready`, then a second 202 `analysing`. The app
accepted only one `analysing` reply, so the first question after every
restart failed. (2) A real answer takes 10–35 s because of the LLM, but chat
requests timed out after 30 s. (3) Answers arrive as Markdown and were
printed as one run-on paragraph. (4) Real recording folders are named like
`4_S800_F35_D0.25`, which the citation parser didn't recognise, so the
provenance trail and Evidence page couldn't show the condition. (5) The
Analysis page didn't show backend errors (e.g. "ingest first"), and leaving
the page lost track of a running job, so later clicks hit "already running".

**Fix:** The chat flow keeps polling while the backend reports `ingesting` or
`analysing`, re-asks when it's done, handles repeated 202s (capped at five
re-asks), and allows 5 minutes for LLM-backed requests. Answers render a safe
Markdown subset (headings, bullets, bold) with citation chips inside. The
path parser understands the real folder layout. The Analysis page shows
backend errors with a link to Dataset Health and re-attaches to a running job
when opened. Mock handlers now follow the real reply sequence.

**Verification:** Reproduced and re-checked each case in a browser against
the real backend; new frontend tests cover each reply sequence and page
behaviour.

## Chat Send reliability — 2026-09-30

**Root cause:** Two separate problems made Send look broken.
(1) Opening the app at the machine's network address
(`http://10.24.14.94:5173`) instead of `localhost` makes it a non-secure page,
where browsers don't provide `crypto.randomUUID()`. The chat used that to
create message IDs, so every Send failed before any request was made; the
error only reached the browser console. (2) While an answer was pending
(10–30 s), the page showed only faint placeholder bars and locked the text box
and Send button, so it looked unresponsive. A page reload mid-question also
left a placeholder that never resolved.

**Fix:** IDs come from a helper that falls back to `crypto.getRandomValues`
(available on plain HTTP). The waiting state now shows a spinner, an elapsed
counter, the expected duration and a Cancel button. The text box stays usable
for the next question, and leftover placeholders from a reload are labelled
as interrupted. Frontend tests pin their own API URLs so a developer's
`.env.local` can't change them.

**Verification:** Send works on the network-address URL in a browser; a
question without a condition shows the backend's guidance, and one with a
condition is answered with citations. Frontend: 43 tests pass, type check and
build clean.

## Merge of `main` into `vaishnavi` — 2026-10-01

**What:** `vaishnavi` (13 Sep) had document-RAG infrastructure: a query
router, weighted hybrid retrieval, a real `pypdf` parser, optional
Qdrant/Neo4j/Anthropic backends, `X-API-Key` auth, structured ingest errors
and an eval harness. `main` had everything built since: the DAQ pipeline,
chat server, web app and caching. `main` was merged into `vaishnavi`.

**Conflicts and how they were resolved:** Eight files conflicted. The key one
was `knowledge/graph_store.py`. `vaishnavi` kept the old dict-based graph
interface, while `main` had moved to typed `GraphEdge` objects that the DAQ
provenance graph and its tests depend on. The resolution keeps `main`'s typed
simulator (with its O(1) edge dedupe) and adds `vaishnavi`'s real Neo4j driver
behind the same typed interface. Document retrieval's `graph_augment()` now
uses the string form. In `api/main.py`, `main`'s DAQ API was kept and
`vaishnavi`'s auth, error handling and RAG-orchestrator change were
re-applied; `/analyse` is behind the same optional key. Config files are
unions of both sides.

**Verification:** backend 53 passed / 2 skipped, `test_step10.py` passes,
`server.py` imports, frontend 43 passed — all before any new feature work.

## Tier-1 knowledge documents — 2026-10-01

**What:** Four explainer PDFs (machine fact sheet, quarantine policy, how a
Finding is computed, glossary) were added under `knowledge_docs/pdfs/`,
indexed at startup, linked to concepts in the graph, and made answerable in
chat. The plan behind this was `Document_Knowledge_Base_Integration_Plan.md`
(Steps 0–5 of the Tier-1 checklist).

**Findings while implementing (checked, not assumed):**
- **PDF extraction was already real on this branch.** `vaishnavi` had
  replaced the simulated parser with `pypdf`; all four PDFs extract their
  actual text. One risk remained: if extraction failed, the parser decoded the
  raw PDF bytes as UTF-8 and would have indexed PDF syntax as content. Real
  PDFs now yield no text (0 chunks, with the reason in metadata) instead.
- **The glossary had to be wired in, not just added.** The existing glossary
  scan only ran on the generic document prompt, required spaces around a
  term (so "…distance?" never matched) and read only `meaning:`. `/chat` also
  rejected any question without a condition and signal, so "What does RMS
  mean?" could not work as the plan expected. The plan's list has 18 terms,
  not 17.
- **Retrieval needed three fixes.** The keyword index didn't strip
  punctuation ("kurtosis?" ≠ "kurtosis"). The router gave 80% weight to
  vector search, but the default embedder hashes text to random vectors, so
  that weight was pure noise. Fixed-width chunking cut words in half. Before
  the fixes, "What's the difference between RMS and kurtosis?" retrieved no
  glossary chunk at all; after, all four test questions retrieve the right
  document first. The keyword fix alone was enough for the glossary
  question; the concept links are a second safeguard.
- **The plan's ontology snippet would have dropped the DAQ types.**
  `Document`/`Concept` and `DOCUMENTS`/`EXPLAINS`/`RELATED_TO` were appended
  instead, keeping `Condition`, `Recording`, `CAPTURED_UNDER` and the rest.
- **Editing `domain.yaml` invalidated every cache.** The dataset fingerprint
  hashed the whole config file, so adding the glossary forced a full
  re-profile of the corpus and re-analysis of every scope. Only the
  parsing/analysis keys feed the fingerprint now, so glossary, ontology and
  prompt edits never do this again. Because the key scheme changed, the
  first start after this change re-profiles once and each scope is
  re-analysed once on first use.

**How:** `ingestion/knowledge_docs.py` indexes the PDFs through the existing
document pipeline at server startup (`POST /knowledge-docs/ingest`
re-indexes; `GET /knowledge-docs` lists them) and writes the concept edges
from a hand-written seed list. `/chat` sends questions without a
condition/signal to `answer_from_documents()`. That retrieves passages,
guarantees a place to any document linked to a concept named in the
question, and asks the LLM for an evidence-only answer citing `[Source N]`.
If nothing relevant is found, it still asks for a condition and signal.
Glossary definitions for terms in the question go into both document and DAQ
prompts. In the DAQ prompt, "condition 4" names a scope, not a term to
define. The web app renders `[Source N]` chips with the cited passage, and
splits grouped markers such as `[Source 1, Source 3]`, which the model
sometimes writes.

**Verification:** 29 new backend tests: real extraction per PDF, chunk word
boundaries, all 18 glossary terms, matching rules, `DOCUMENTS` edges, the
right document first for each test question, `/chat` routing, and cache
fingerprint stability. 7 new frontend tests. Live with Gemini: "What does RMS
mean?" was answered from the glossary, "Why do some recordings get
quarantined?" from the policy explainer, and "Condition 4 has an unusually
high recording count — is that expected?" from the fact sheet (yes: counts
range from 24 to 39, and condition 4 has 39). All rendered in the browser
with source chips and passages.

**Not done (deliberately):** mixed answers combining findings and passages;
layout-aware extraction (Docling) for exact table rows; semantic embeddings
by default.
