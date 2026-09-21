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
