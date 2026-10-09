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

### Unified Knowledge Graph Architecture

The knowledge graph spans three unified data sources:
```
People ↔ Emails ↔ CNC Components ↔ Documentation ↔ Processes ↔ Sessions ↔ Sensor Data ↔ Events
```

### End-to-End Query Pipeline

```
[User Query]
      │
      ▼
① Understand intent/entities (Step 1) ── NER/entity matching against unified ontology + Session addressing (Option A)
      │
      ▼
② Validate CNC context (Step 2) ── Strict CNC scope gate (declines out-of-scope queries with fixed declaration)
      │
      ▼
③ Traverse knowledge graph (Step 3) ── Multi-hop traversal starting from query-extracted seed entities
      │
      ▼
④ Retrieve relevant data (Step 4) ── Passage-level text (Vector/BM25) + Sensor/signal analytics
      │
      ▼
⑤ Analyze/reason (Step 5) ── Cross-source reasoning (corroborate findings, match faults, link communications)
      │
      ▼
⑥ Generate grounded answer (Step 6) ── Evidence-only synthesis with transparent citations and provenance
```

### Underlying Processing & Provenance Pipeline

```
 DAQ recordings (25 condition folders, CSV files) + Documentation (PDFs) + Email Corpus
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
 ⑥ Unified Provenance Graph ── Session ↔ Event ↔ Finding ↔ Fault ↔ Component ↔ Document ↔ Person ↔ Email
        │
        ▼
 ⑦ Evidence-only LLM ── explains findings & cross-source relations in plain language with citations
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

### Project knowledge documents

Short explainer PDFs in `knowledge_docs/pdfs/` let the assistant answer
questions *about* the project as well as about specific runs:

| Document | Explains |
|---|---|
| `machine_fact_sheet.pdf` | The S/F/D settings, the 25 conditions as a 5×5 Latin-square experiment, recording counts per condition, raw-voltage channels, sampling rate |
| `quarantine_policy_explainer.pdf` | Why files are quarantined instead of repaired, and the rejection reasons |
| `finding_explainer.pdf` | How a Finding is computed, step by step, in plain language |
| `glossary.pdf` | RMS, kurtosis, crest factor, spectral features, Mahalanobis distance and other terms |

At startup, the chat server extracts their text, splits it into chunks,
indexes the chunks for keyword search, and links each document to the
concepts it explains in the knowledge graph (`Document -[:DOCUMENTS]->
Concept`). The glossary terms are also in `config/domain.yaml`. When a
question uses one, its definition goes into the prompt, so "what does RMS
mean?" gets the project's own definition. These documents contain
explanations only, never measurements from individual runs.

To add a document, drop the PDF into `knowledge_docs/pdfs/` and restart, or
call `POST /knowledge-docs/ingest`. To link it to concepts, add it to
`CONCEPTS_PER_DOC` in `ingestion/knowledge_docs.py`.

---

## 3. What happens when you ask a question

The chat server first works out what kind of question it is:

- **About a specific run's behaviour.** The question names **one condition
  number and one signal**: "condition 4" plus "spindle vibration", "X load",
  "motor current" and so on. It is answered from computed findings, as
  described below. Findings are cited as `[Finding N]`.
- **About the project, machine or vocabulary.** Anything else, such as
  *"What does kurtosis mean?"*, *"Why are files quarantined?"* or
  *"Condition 4 has a lot of recordings — is that expected?"*. It is
  answered from the knowledge documents, citing passages as `[Source N]`.
  If the documents don't cover it either, the server asks for a condition
  and a signal.

For a run-specific question:

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
- **Node.js 18+ / 20+ / 22** (for the React web frontend)
- An API key for **Gemini** (default: `GEMINI_API_KEY`) or **OpenAI** (`OPENAI_API_KEY`)
- **Zero Cloud Services Needed**: Runs 100% locally with embedded in-memory Neo4j graph and local vector store.
- **Zero Dataset Download Needed (Dataset-Free Mode)**: The Git repository tracks all 7 technical PDF manuals, 6 machine maintenance emails, the domain ontology, and pre-trained tool-wear ML models out of the box. (Raw multi-GB sensor CSVs are optional and only needed if re-computing raw DAQ signal windows from scratch).

### Quickstart on Any New Machine (Git-Only Setup)

#### 1. Clone the repository
```bash
git clone https://github.com/1vedantshinde/institutional-memory.git
cd institutional-memory
```

#### 2. Setup Python environment & dependencies
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```
Open `.env` and enter your Gemini API key:
```ini
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_actual_gemini_api_key_here
GEMINI_MODEL=gemini-3.8-flash
```

#### 3. Setup Frontend
```bash
cd frontend
npm install
cp .env.example .env.local
cd ..
```
*(Ensure `frontend/.env.local` points `VITE_CHAT_API_URL=http://localhost:8000` and `VITE_CORE_API_URL=http://localhost:8000`)*

#### 4. (Optional) Run One-Command Ingestion & Verification
```bash
python3 all_ingest.py
```
This indexes the tracked PDF manuals, filters and loads the machine operational emails, and builds the in-memory knowledge graph.

#### 5. Launch the System

**Terminal 1 — Backend API & Knowledge Server:**
```bash
source .venv/bin/activate
python3 -m uvicorn server:app --reload --port 8000
```

**Terminal 2 — React Web Dashboard:**
```bash
cd frontend
npm run dev
```

Open **http://localhost:5173** in your browser. You can immediately ask questions about machine operations, technical manuals, spindle maintenance logs, calibration, and vibration alerts!

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
| `LLM_PROVIDER` | `gemini` (default), `openai` or `anthropic`. `mock` is for tests only; the chat refuses to answer with it. |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Gemini credentials and primary model. |
| `GEMINI_FALLBACK_MODELS` | Comma-separated models to try in order when the primary is temporarily unavailable (overloaded, rate-limited, network drop). Invalid-key or bad-request errors are never retried. |
| `GEMINI_MAX_RETRIES` | Retries for the last model in the list. Earlier models are tried once each so a busy model doesn't stall the answer. |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | OpenAI alternative. |
| `ANTHROPIC_API_KEY` | Anthropic alternative. |
| `DAQ_DATASET_ROOT`, `DAQ_CONFIG_PATH` | Dataset and config locations (default `dataset/Readngs_DAQ_Data`, `config/domain.yaml`). |
| `DAQ_WARM_START` | Set to `0` to stop the chat server loading the dataset inventory at startup. |
| `KNOWLEDGE_DOCS_ENABLED` | Set to `0` to skip indexing `knowledge_docs/pdfs/` (general questions then get the "name a condition and signal" reply). |
| `API_KEY` | When set, write endpoints (`/ingest`, `/ingest-folder`, `/analyse`, `PUT /config`, `/knowledge-docs/ingest`, legacy ingest) require an `X-API-Key` header. The web app doesn't send one yet, so leave it empty for local use. |
| `QDRANT_URL`, `NEO4J_URI` (+ user/password), `USE_NEURAL_MODELS`, `EMBEDDING_DIM` | Optional real infrastructure for the document knowledge base. Without them, in-memory equivalents are used. `docker compose up -d` starts Qdrant and Neo4j. |

### Domain configuration (`config/domain.yaml`)

This file describes the domain rather than the code: the canonical channel
names and expected column count, the folder-name pattern that encodes
condition/S/F/D, quality-gate policy, feature bands, windowing defaults, the
graph's entity and relation types (including `Document`/`Concept` and
`DOCUMENTS`), the glossary, and the LLM's system instruction. It can be viewed
and hot-reloaded through `GET/PUT /config` or the Config page. Only the
parsing/analysis keys feed the cache fingerprint, so glossary, ontology or
prompt edits never force a re-analysis. Saving through `PUT /config` rewrites
the file, so YAML comments in it are not preserved.

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
| `GET /knowledge-docs` | Indexed knowledge documents, their chunk counts and linked concepts. |
| `POST /knowledge-docs/ingest` | Re-index `knowledge_docs/pdfs/` after adding or replacing a PDF. |
| `POST /ingest-folder`, `/ingest/file`, `/ingest/graph` | Document knowledge base: index any supported documents (PDF, DXF, e-mail, Python) or inject validated graph nodes/edges. |

Answers use the same shape everywhere: `answer` (Markdown text with
`[Finding N]` or `[Source N]` markers), `citations` (findings: finding ID,
model version, source file, channel, window, sample range and, when
confirmed, time range), `finding_count`, and, for document answers,
`sources` (label, file, passage) with `route: "documents"`.

---

## 8. Speed and caching

Reading 41 GB is slow, so derived results are saved under
`runtime/daq_cache/` (git-ignored):

- **Ingestion cache.** The inventory is keyed by a fingerprint of every file's
  path, size and modification time, plus the config keys that affect parsing
  and analysis. An unchanged dataset
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
| Backend | `python3 -m pytest -q` | Quality gate, windowing, features, baselines, anomalies, leakage-safe splits, graph, retrieval, evidence-only prompting, API, chat scope parsing, cache reuse, LLM fallback, and the knowledge documents (real text extraction, chunking, glossary matching, `DOCUMENTS` edges, per-question retrieval, `/chat` routing). Uses small synthetic data plus the committed PDFs, so no dataset is needed. |
| Document retrieval eval | `python3 eval/run_eval.py` | Recall@8, query routing and answer confidence over `eval/golden_set.json`. Fill in real `expected_doc_ids` first; until then it reports failures by design. |
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
| `analytics/` | Per-condition baselines, anomaly detection, leakage-safe splits, session analytics triggering & cross-source reasoning (`session_analyzer.py`), tool-wear model. |
| `knowledge/` | Provenance graph (ontology, graph store: in-memory or Neo4j), `provenance.py`, `session_ids.py` (global 1..822 addressing), and entity extraction. |
| `retrieval/` | Query intent & entity understanding (`query_understanding.py`), strict CNC scope gate (`scope_gate.py`), multi-hop knowledge graph traversal (`graph_query.py`), node-guided data retrieval (`node_data_retriever.py`), DAQ metadata index, feature store and retriever; document hybrid retrieval. |
| `llm/` | Evidence-only prompt builders (findings and documents) and orchestrators; extra LLM providers (Anthropic). |
| `core/` | Shared data models, config loading/hot-reload, and plugin registries (including the Gemini/OpenAI providers). |
| `knowledge_docs/pdfs/` | Project knowledge documents answered from in chat (see §2). |
| `ingestion/knowledge_docs.py` | Indexes those PDFs and links them to concepts. |
| `eval/` | Document-retrieval evaluation harness and golden questions. |
| `docker-compose.yml` | Optional Qdrant + Neo4j services. |
| `config/domain.yaml` | Domain configuration (see §6). |
| `train_tool_wear_model.py` | Command-line training and evaluation for the tool-wear model. |
| `frontend/` | React web app (see its README). |
| `tests/` | Backend test suite. |
| `runtime/`, `artifacts/`, `quarantine/`, `uploads/` | Generated locally: caches, trained models, rejection logs, uploads. Git-ignored. |
| `KNOWLEDGE_BASE.md`, `progress.md` | Blueprint and build log. |

The document parsers (PDF, DXF/CAD, e-mail, Python) and text retrieval come
from the platform's general-purpose design. The project knowledge documents
use them, and they can index any other supported documents.
The scripts about **MyFixit / Qwen** (`train*.py`, `evaluate_qwen.py`,
`golden_test_suite.py`, `build_kg.py`, `graph_retriever.py`, `yimplement.py`,
`test.py`) are a separate, earlier experiment: a repair-manual assistant. They
aren't part of the DAQ application.

---

## 11. Current status, limitations and roadmap

**Working today**

- **Unified Knowledge Graph Query Pipeline (Steps 1–6 complete)**:
  - Step 1: Query intent & entity understanding with ontology NER and Option A session addressing (`retrieval/query_understanding.py`).
  - Step 2: Strict CNC scope gate with 3-tier validation and verbatim `IN_SCOPE_DECLARE` decline (`retrieval/scope_gate.py`).
  - Step 3: Multi-hop knowledge graph traversal with bounded BFS and cycle prevention (`retrieval/graph_query.py`).
  - Step 4: Node-guided cross-modal data retrieval combining BM25, vector search, and signal findings (`retrieval/node_data_retriever.py`).
  - Step 5: Session analytics triggering (`ensure_session_analysis`) and cross-source evidence synthesis (`analytics/session_analyzer.py`).
  - Step 6: Multi-source grounded answer generation citing `[Finding N]`, `[Doc N]`, and `[Email N]` (`llm/prompt_builder.py` & `llm/orchestrator.py`).
- Full pipeline from raw CSV to cited explanation, verified on the real corpus.
- Chat server with automatic ingestion/analysis, cache reuse and LLM fallback.
- Web app with all six pages, mock mode and automated tests.
- Questions about the project, machine and terms answered from the knowledge documents, with cited passages.
- Tool-wear model: on 161 held-out recordings it scored MAE 14.3 µm, RMSE 18.9 µm, R² 0.93 (split by whole recordings, so no window leakage).

**Known limitations**

- **Document search is keyword-based by default.** The default embedder isn't semantic, so vector search is switched off unless `USE_NEURAL_MODELS=1`.
- **The first analysis of a new condition + channel takes time.** Every answer after that uses the cache.
- **Load-cell and current answers can use vibration wording.** Plain-language feature statements currently say "vibration" for every channel. The numbers are right; the wording needs to become channel-aware.
- **Local use only.** The backend accepts connections only from the same machine.
- **The tool-wear split is not by condition.** It separates whole recordings, but held-out recordings can share a condition with training ones.

**Next steps**

1. **Ingestion Pipelines**: Production PDF entity extraction (`extraction/doc_entity_extraction.py`) and email archive ingestion (`ingestion/parsers/email_parser.py`, `ingestion/extraction/ner.py`).
2. Channel-aware wording for findings (load, current and vibration).
3. Serve the tool-wear model through the API and connect the Tool Wear page.
4. Endpoints for listing conditions, listing findings and fetching a window's waveform, then enabling the Waveforms page. See [frontend/BACKEND_REQUESTS.md](frontend/BACKEND_REQUESTS.md).
5. Optional LAN access (bind the backend to the network and allow the frontend's origin).
6. Multi-signal and cross-condition questions.
7. Layout-aware PDF extraction (e.g. Docling), so table rows such as per-condition recording counts can be retrieved exactly.

---

## 12. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Address already in use` when starting a server | Another copy is already running on that port. Stop it (`ss -ltnp` shows who owns the port) or use a different port. |
| Status dots in the app are red | The backend isn't running, or the URLs in `frontend/.env.local` or the Settings drawer point to the wrong port. |
| Chat says "State both a condition and one signal" | The question wasn't about a specific run, and the knowledge documents don't cover it. For measured behaviour, include a condition number and a signal, e.g. *"motor current for condition 4"*. |
| A general question gets no document answer | Check `GET /knowledge-docs` lists the PDFs. If not, check the startup log line `[KnowledgeDocs]`, or call `POST /knowledge-docs/ingest`. |
| "The language model is busy or not configured" | The provider returned 503/429, or the API key is missing. Retry, or set `GEMINI_FALLBACK_MODELS`. |
| Answer takes a long time the first time | That condition and signal is being analysed for the first time. The progress card shows it, and later questions are fast. |
| Analysis page shows "already running" | Only one analysis runs at a time. The page follows the running job and you can start yours when it finishes. |
| Changed data but results didn't change | Use **force** on ingestion/analysis. The cache follows file size and modification time, not file contents. |
