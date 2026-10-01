# Institutional Memory — DAQ Condition Intelligence

Institutional Memory explains unusual behaviour in CNC-machining sensor
recordings. An operator asks a plain-language question such as *"What changed
in spindle vibration for condition 4?"* and gets a short answer. Every claim in
the answer links back to the exact recording, sensor channel and time window it
came from.

The rule the whole design follows: **the AI explains, it never calculates.**
Every number (sampling rates, features, baselines, anomaly scores) is computed
by deterministic Python analytics. The language model only turns those
already-computed findings into readable sentences, and it is told never to
estimate, derive or invent a value.

> For a step-by-step history of how each part was built and verified, see
> [progress.md](progress.md). For the original architectural blueprint, see
> [KNOWLEDGE_BASE.md](KNOWLEDGE_BASE.md).

---

## Contents

1. [The problem and the approach](#1-the-problem-and-the-approach)
2. [How it works, end to end](#2-how-it-works-end-to-end)
3. [What happens when you ask a question](#3-what-happens-when-you-ask-a-question)
4. [The web app](#4-the-web-app)
5. [Getting started](#5-getting-started)
6. [Configuration](#6-configuration)
7. [Using the API directly](#7-using-the-api-directly)
8. [Speed and caching](#8-speed-and-caching)
9. [Testing](#9-testing)
10. [Repository map](#10-repository-map)
11. [Current status, limitations and roadmap](#11-current-status-limitations-and-roadmap)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. The problem and the approach

A CNC machine was run under **25 process conditions**. Each condition is one
combination of spindle speed (**S**), feed (**F**) and depth of cut (**D**).
Each run was captured as a CSV **recording** with seven columns: a time axis
plus six sensor channels.

| Channel | What it measures |
|---|---|
| `Vib_Spindle` | Spindle vibration |
| `Vib_Table` | Table vibration |
| `X_Load_Cell`, `Y_Load_Cell`, `Z_Load_Cell` | Cutting force on each axis |
| `Current` | Motor current |

The full corpus has **822 recordings (about 41 GB)**. A tool-wear
measurement table gives the actual tool wear (in µm) for each run.

Language models are good at explaining and bad at arithmetic on long numeric
signals. Asked directly about raw sensor data, they will produce confident
numbers that were never measured. So the project splits the work:

1. **Deterministic analytics** turn raw signals into traceable *findings*
   ("this 2,048-sample window of spindle vibration in recording 12 departs
   from the normal profile for this condition, mainly in low-frequency
   energy").
2. **A provenance graph and index** keep every finding linked to its window,
   recording and condition.
3. **An evidence-only LLM step** receives only those findings, their
   plain-language statements and their provenance, and writes the
   explanation, citing each finding as `[Finding N]`.

A second rule matters just as much: **"normal" is defined per condition.**
Changing speed, feed or depth legitimately changes vibration, load and
current. Each condition therefore gets its own baseline, so a different
setting is never mistaken for a fault.

---

## 2. How it works, end to end

```
 DAQ recordings (25 condition folders, CSV files)
        │
        ▼
 ① Ingestion & quality gate ── bad files are quarantined, never "repaired"
        │
        ▼
 ② Signal processing ── sampling rate, gap filling, 2,048-sample windows
        │
        ▼
 ③ Features ── time-domain statistics + frequency-band energy per window
        │
        ▼
 ④ Per-condition baselines ── "normal" for each (condition, channel) pair
        │
        ▼
 ⑤ Anomaly detection ── windows far from their baseline become Findings
        │
        ▼
 ⑥ Provenance graph + indexes ── Condition → Recording → Window → Finding
        │
        ▼
 ⑦ Evidence-only LLM ── explains findings in plain language, with citations
        │
        ▼
 ⑧ API + web app ── chat, dataset health, analysis, evidence browser
```

**① Ingestion and quality gate.** The dataset is discovered from its folder
names. Each condition folder is named like `4_S800_F35_D0.25`, which encodes
condition 4 at speed 800, feed 35 and depth 0.25. The pattern is configurable.
Every CSV is checked before any analysis: raw bytes are checksummed, stray
null bytes are removed and logged, and the header, column count and numeric
values are validated. A file that fails is **quarantined** with a logged
reason (for example `column_count_mismatch:4` or `unparseable_csv`). It is
never coerced into the seven-channel format. In the last full profile, 805
recordings passed and 17 were quarantined.

**② Signal processing.** The sampling rate is measured from the time column,
never assumed. Short gaps are filled per channel. Each channel is cut into
windows of 2,048 samples with 50% overlap. Every window remembers its exact
sample range and, when the time axis is trustworthy, its time range.

**③ Features.** Each window gets time-domain statistics (mean, spread, RMS,
peak, crest factor, kurtosis, skewness). When the sampling rate is valid, it
also gets frequency features (low/mid/high band energy and spectral centroid).
If the rate can't be confirmed, frequency features are skipped rather than
guessed.

**④ Baselines.** For every (condition, channel) pair, the mean and spread of
each feature are computed from **canonical recordings only**. No global
baseline is used.

**⑤ Anomaly detection.** Each window is scored by its distance from its own
condition's baseline, using a diagonal Mahalanobis distance (model version
`mahalanobis-diagonal-v3`). Windows above the threshold (3.0 by default)
become **Findings**. A Finding records where it came from and which features
moved most, already phrased in plain language ("low-frequency vibration
energy above the condition baseline").

**⑥ Provenance and retrieval.** Findings are linked in an in-memory graph
(Condition → Recording → SignalWindow → Finding). Exact metadata filters
(condition, channel, recording) select what a question is about, and a
feature store supports similar-window search.

**⑦ Explanation.** The LLM receives the selected Findings, their statements
and short provenance. Nothing else goes in: no raw signal arrays and no
free-form data. It writes a short summary with representative findings
marked `[Finding N]`. Citations are built from the Findings themselves, not
parsed from the LLM's text, so they can't be invented.

**⑧ Serving.** A FastAPI backend exposes everything over HTTP, and a React
web app sits on top.

### Separate module: tool-wear prediction

A supervised regression model (gradient-boosted trees) predicts tool wear in
µm from each recording's computed signal features plus its S/F/D settings. It
trains from the command line and writes a model and an evaluation report
locally. It is **not yet served by the API** (see §11).

---

## 3. What happens when you ask a question

The chat server works out the scope from the question itself. It needs
**one condition number and one signal**: "condition 4" plus "spindle
vibration", "X load", "motor current" and so on. Without both, it replies
with a short message asking for them.

```
Question ──► Is the dataset inventory loaded?
                 no  → reply "ingesting"; load it (seconds when cached)
                 yes ▼
             Are findings for this condition + signal in memory?
                 yes → answer now
                 no  ▼
             Is there a saved analysis on disk that covers it?
                 yes → load it (about 1 s) and answer now
                 no  → reply "analysing"; run the analysis in the background
                        (minutes, only the first time for this scope)
```

When the backend replies "ingesting" or "analysing", the web app shows a
progress card, checks the status every 2 seconds, and re-asks automatically
when the work is done. A question on a scope that is already prepared usually
takes **10–30 seconds**, almost all of it the language model.

---

## 4. The web app

| Page | What it's for |
|---|---|
| **Ask** | The chat. Answers show clickable citation chips (F1, F2…). Clicking one opens an evidence panel with the provenance trail (condition → recording → window → finding), source file, sample range and time range. A "scoped query" option lets you pick the condition, channel and number of findings explicitly. |
| **Dataset Health** | Runs ingestion and shows discovered / canonical / quarantined counts, the quarantine rate and a chart of rejection reasons. |
| **Analysis** | Starts an anomaly analysis for a chosen condition and channels, shows its progress, and hands off to Ask with a ready-made question. If you leave and come back, it picks up a running job. |
| **Evidence** | Every citation seen this session, filterable, exportable to CSV or JSON. |
| **Config** | Views and edits the domain configuration. Saving shows which top-level keys will change and asks for confirmation; the backend reloads it without a restart. |
| **About** | The pipeline and the three rules: deterministic analytics, traceable provenance, evidence-only explanations. |

The app also has dark and light themes, works on phones (360 px), supports
keyboard navigation, and can run entirely on **mock data** with no backend,
which is useful for UI work and demos. Two extra preview pages (waveforms and
tool wear) appear only with mock data, because their backend endpoints don't
exist yet.

Frontend-specific details: [frontend/README.md](frontend/README.md).

---

## 5. Getting started

### What you need

- **Python 3.10+**
- **Node.js 22** (for the web app)
- An API key for **Gemini** (default) or **OpenAI**
- The DAQ dataset, placed at `dataset/Readngs_DAQ_Data/`, with one folder per
  condition, each holding `Recording <N>.csv` files. The data is not in the
  repository and is git-ignored.

### One-time setup

```bash
python3 -m pip install -r requirements.txt
cp .env.example .env                  # then add your API key (see §6)

cd frontend
npm install
cp .env.example .env.local            # then set VITE_CORE_API_URL (see below)
```

In `frontend/.env.local`, point **both** URLs at the one backend:

```
VITE_CHAT_API_URL=http://localhost:8000
VITE_CORE_API_URL=http://localhost:8000
```

### Every time

Terminal 1, at the repository root:

```bash
python3 -m uvicorn server:app --reload --port 8000
```

Terminal 2:

```bash
cd frontend && npm run dev
```

Open **http://localhost:5173** and ask something like *"Which windows look
abnormal in the X load cell for condition 7?"*.

**Why one backend?** `server.py` serves the chat endpoints *and* every core
endpoint (`/ingest`, `/profile`, `/analyse`, `/query`, `/config`). Running
`api/main.py` as a second server on another port gives it a separate memory:
analyses started from one aren't visible to the other, and each ingests the
dataset separately. The second entrypoint remains for headless or scripted
use.

### No backend? Use mock mode

Set `VITE_USE_MOCKS=true` in `frontend/.env.local` and run only
`npm run dev`. Every page works on realistic sample data, and the UI marks it
as mock data.

---

## 6. Configuration

### Backend (`.env` at the repository root; `.env.example` lists every option)

| Variable | Purpose |
|---|---|
| `LLM_PROVIDER` | `gemini` (default) or `openai`. `mock` is for tests only; the DAQ query path refuses to answer with it. |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Gemini credentials and primary model. |
| `GEMINI_FALLBACK_MODELS` | Comma-separated models to try in order when the primary is temporarily unavailable (overloaded, rate-limited, network drop). Invalid-key or bad-request errors are never retried. |
| `GEMINI_MAX_RETRIES` | Retries for the last model in the list. Earlier models are tried once each so a busy model doesn't stall the answer. |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | OpenAI alternative. |
| `DAQ_DATASET_ROOT`, `DAQ_CONFIG_PATH` | Dataset and config locations (default `dataset/Readngs_DAQ_Data`, `config/domain.yaml`). |
| `DAQ_WARM_START` | Set to `0` to stop the chat server loading the dataset inventory at startup. |

### Domain configuration (`config/domain.yaml`)

This file describes the domain rather than the code: the canonical channel
names and expected column count, the folder-name pattern that encodes
condition/S/F/D, quality-gate policy, feature bands, windowing defaults, the
graph's entity and relation types, and the LLM's system instruction. It can
be viewed and hot-reloaded through `GET/PUT /config` or the Config page.

### Frontend (`frontend/.env.local`; `frontend/.env.example` lists every option)

`VITE_CHAT_API_URL`, `VITE_CORE_API_URL`, `VITE_USE_MOCKS`,
`VITE_ENABLE_PROPOSED`, the default dataset/config paths shown on Dataset
Health, and `PORT` (default 5173). The backend URLs can also be changed at
runtime in the app's Settings drawer (gear icon); saved values there take
priority.

---

## 7. Using the API directly

Everything the web app does is available over HTTP, which suits scripts and
automated checks. Interactive documentation is served at
**http://localhost:8000/docs** while the backend runs.

| Endpoint | Purpose |
|---|---|
| `POST /chat` | Ask a question. Returns **200** with an answer and citations, or **202** with `ingesting` / `analysing` while it prepares; re-ask when ready. |
| `GET /chat/status` | Preparation status: `ingesting`, `analysing`, `ready`, `analysis_ready`. |
| `POST /ingest` | Start a background profile of the dataset (returns 202). `force` bypasses the cache. |
| `GET /profile` | Ingestion summary: discovered, canonical, quarantined and reasons. Returns 404 until the first ingestion. |
| `POST /analyse` | Start a background analysis for a condition and optional channels, with window size, overlap and threshold. Returns 409 if one is already running. |
| `GET /analyse/status` | `idle`, `running`, `complete` (with counts) or an error. |
| `POST /query` | Scoped question with explicit `condition_id` / `channel` filters and `top_k`. |
| `GET` / `PUT /config` | Read or hot-reload the domain configuration. |

Answers use the same shape everywhere: `answer` (Markdown text with
`[Finding N]` markers), `citations` (each with finding ID, model version,
source file, channel, window, sample range and, when confirmed, time range)
and `finding_count`.

---

## 8. Speed and caching

Reading 41 GB is slow, so derived results are saved under
`runtime/daq_cache/` (git-ignored):

- **Ingestion cache.** The inventory is keyed by a fingerprint of every file's
  path, size and modification time plus the config. An unchanged dataset
  reloads in about 1.5 seconds; any change triggers a fresh profile.
- **Analysis cache.** Windows, features, baselines and findings are saved per
  analysis scope and settings. When you ask a question, any saved analysis
  that *covers* it is reused: an exact match, the whole condition, the whole
  channel or the whole dataset. That's safe because baselines and findings are
  computed per (condition, channel), so a broader run gives identical findings
  for that pair.
- **In-memory merging.** Scopes you've asked about stay loaded together, so
  switching between conditions is instant.

Rough timings on the current machine:

| Situation | Time |
|---|---|
| Server start → inventory ready | ~1.5 s |
| First-ever analysis of a condition + channel | ~30 s to several minutes, depending on data volume |
| Loading a saved analysis | ~1 s |
| Answer once evidence is ready | ~10–30 s (the language model) |

To force a recompute after changing the data, send `"force": true` to
`/ingest` or `/analyse`, or use the switch on those pages.

---

## 9. Testing

| Suite | Command | Covers |
|---|---|---|
| Backend | `python3 -m pytest -q` | Quality gate, windowing, features, baselines, anomalies, leakage-safe splits, graph, retrieval, evidence-only prompting, API, chat scope parsing, cache reuse, LLM fallback. Uses small synthetic data, so no dataset is needed. |
| Live-data checks | `DAQ_DATASET_ROOT=… python3 -m pytest -q tests/test_manifest.py tests/test_quality.py` | Runs the manifest and quality gate against the real corpus when it's mounted. |
| Frontend | `cd frontend && npx vitest run` | Chat flow (all backend states), Dataset/Analysis/Config pages, parsing and rendering, run against mock HTTP handlers. |
| Frontend types / build | `npx tsc --noEmit`, `npx vite build` | Type safety and production bundle. |

---

## 10. Repository map

| Path | Role |
|---|---|
| `server.py` | Main backend entrypoint. Chat endpoints, scope detection, automatic ingest/analysis, cache reuse, warm start. Includes every core endpoint. |
| `api/main.py` | Core FastAPI app: ingest, profile, analyse, query and config, background jobs and caching. |
| `ingestion/` | Dataset discovery (manifest), CSV quality gate, DAQ parser and pipeline. |
| `signal/` | Sampling rate, gap filling, windowing and features. |
| `analytics/` | Per-condition baselines, anomaly detection, leakage-safe splits, tool-wear model. |
| `knowledge/` | Provenance graph (ontology and in-memory graph store). |
| `retrieval/` | Metadata index, feature store and DAQ retriever. |
| `llm/` | Evidence-only prompt builder and explanation orchestrator. |
| `core/` | Shared data models, config loading/hot-reload, and plugin registries (including the Gemini/OpenAI providers). |
| `config/domain.yaml` | Domain configuration (see §6). |
| `train_tool_wear_model.py` | Command-line training and evaluation for the tool-wear model. |
| `frontend/` | React web app (see its README). |
| `tests/` | Backend test suite. |
| `runtime/`, `artifacts/`, `quarantine/`, `uploads/` | Generated locally: caches, trained models, rejection logs, uploads. Git-ignored. |
| `KNOWLEDGE_BASE.md`, `progress.md` | Blueprint and build log. |

The document/PDF/CAD/e-mail parsers and text retrieval pieces come from the
platform's original general-purpose design and are kept for compatibility.
The scripts about **MyFixit / Qwen** (`train*.py`, `evaluate_qwen.py`,
`golden_test_suite.py`, `build_kg.py`, `graph_retriever.py`, `yimplement.py`,
`test.py`) are a separate, earlier experiment: a repair-manual assistant. They
aren't part of the DAQ application.

---

## 11. Current status, limitations and roadmap

**Working today**

- Full pipeline from raw CSV to cited explanation, verified on the real
  corpus.
- Chat server with automatic ingestion/analysis, cache reuse and LLM fallback.
- Web app with all six pages, mock mode and automated tests.
- Tool-wear model: on 161 held-out recordings it scored MAE 14.3 µm,
  RMSE 18.9 µm, R² 0.93 (split by whole recordings, so no window leakage).

**Known limitations**

- **Questions must name one condition and one signal.** Comparisons across
  signals or conditions aren't supported yet.
- **The first analysis of a new condition + channel takes time.** Every
  answer after that uses the cache.
- **Load-cell and current answers can use vibration wording.** Plain-language
  feature statements currently say "vibration" for every channel. The
  numbers are right; the wording needs to become channel-aware.
- **Local use only.** The backend accepts connections only from the same
  machine, so another computer on the network can open the web app but can't
  reach the backend.
- **The tool-wear split is not by condition.** It separates whole recordings,
  but held-out recordings can share a condition with training ones. A
  whole-condition hold-out would be a stricter test. The model isn't exposed
  by the API or UI yet.
- **The LLM provider can be busy.** Gemini models are sometimes overloaded;
  configure fallback models (§6).

**Next steps**

1. Channel-aware wording for findings (load, current and vibration).
2. Serve the tool-wear model through the API and connect the Tool Wear page.
3. Endpoints for listing conditions, listing findings and fetching a window's
   waveform, then enabling the Waveforms page. See
   [frontend/BACKEND_REQUESTS.md](frontend/BACKEND_REQUESTS.md).
4. Optional LAN access (bind the backend to the network and allow the
   frontend's origin).
5. Multi-signal and cross-condition questions.

---

## 12. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Address already in use` when starting a server | Another copy is already running on that port. Stop it (`ss -ltnp` shows who owns the port) or use a different port. |
| Status dots in the app are red | The backend isn't running, or the URLs in `frontend/.env.local` or the Settings drawer point to the wrong port. |
| Chat says "State both a condition and one signal" | Include a condition number and a signal, e.g. *"motor current for condition 4"*. |
| "The language model is busy or not configured" | The provider returned 503/429, or the API key is missing. Retry, or set `GEMINI_FALLBACK_MODELS`. |
| Answer takes a long time the first time | That condition and signal is being analysed for the first time. The progress card shows it, and later questions are fast. |
| Analysis page shows "already running" | Only one analysis runs at a time. The page follows the running job and you can start yours when it finishes. |
| Changed data but results didn't change | Use **force** on ingestion/analysis. The cache follows file size and modification time, not file contents. |
