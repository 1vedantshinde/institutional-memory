# Institutional Memory — Industrial Knowledge Intelligence Platform

**Institutional Memory** is a decoupled, format-agnostic, zero-hallucination industrial intelligence platform. It bridges high-frequency Data Acquisition (DAQ) physical sensor signals (vibration, load cell, motor current), process settings, condition-aware baseline modeling, unsupervised anomaly detection, and tool-wear regression with evidence-grounded Large Language Model (LLM) explanations.

---

## Table of Contents

- [Core Philosophy & Architecture](#core-philosophy--architecture)
- [Quickstart: How to Start the Project](#quickstart-how-to-start-the-project)
- [API Key Configuration & Headless Usage](#api-key-configuration--headless-usage)
  - [1. Setting Up `.env`](#1-setting-up-env)
  - [2. Interactive Headless Usage via API / cURL](#2-interactive-headless-usage-via-api--curl)
- [What Results to Expect](#what-results-to-expect)
  - [1. Quality Gating & Inventory Profiling](#1-quality-gating--inventory-profiling)
  - [2. Signal Analytics & Baseline Anomaly Detection](#2-signal-analytics--baseline-anomaly-detection)
  - [3. Evidence-Grounded Conversational Explanations](#3-evidence-grounded-conversational-explanations)
  - [4. Supervised Tool-Wear Regression](#4-supervised-tool-wear-regression)
  - [5. Persistent Local Caching](#5-persistent-local-caching)
- [Repository & Module Structure](#repository--module-structure)
  - [Directory Tree](#directory-tree)
  - [Module Responsibilities](#module-responsibilities)
- [Future Plans & Roadmap](#future-plans--roadmap)

---

## Core Philosophy & Architecture

Standard LLMs struggle with numerical sensor signals because language models are not deterministic math engines. **Institutional Memory** strictly enforces a **Zero Hallucination / No Signal Math** architecture:

1. **Deterministic Analytics Core**: All raw signal preprocessing (NaN interpolation, $f_s$ calculation), sliding windowing (2048 samples, 50% overlap), feature extraction (time & FFT frequency domains), condition-specific baseline fitting, and Mahalanobis anomaly detection take place in deterministic Python code.
2. **Traceable Knowledge & Graph Provenance**: Every anomaly generates a strongly typed `Finding` object linked to a `SignalWindow`, a `Recording`, and a process `Condition` $(S, F, D)$ inside an in-memory Graph Store and Vector Feature Store.
3. **Evidence-Grounded LLM Explanations**: The LLM (OpenAI or Gemini) receives **only** pre-calculated diagnostic statements, condition metadata, and graph context. It is strictly instructed never to derive, estimate, or compute numbers, citing deterministic finding IDs (`[Finding 1]`) backed by structured citations.

```
+------------------------------------------------------------------------------------+
|                                    DAQ Dataset                                     |
|                       (25 Conditions, 822 CSV Recordings)                          |
+------------------------------------------------------------------------------------+
                                         |
                                         v
+------------------------------------------------------------------------------------+
|                          Ingestion & CSV Quality Gate                              |
|          (Raw Byte Checksum, NUL Sanitization, Header & Channel Validation)        |
+------------------------------------------------------------------------------------+
                                         |
                                         v
+------------------------------------------------------------------------------------+
|                         Signal Processing & Analytics                              |
|    (fs Extraction, 2048-sample Windowing, Time/FFT Features, Baselines,            |
|                   Diagonal Mahalanobis Anomaly Detection v3)                       |
+------------------------------------------------------------------------------------+
                                         |
                                         v
+------------------------------------------------------------------------------------+
|                        Metadata Index & Provenance Graph                           |
|       Condition -> Recording -> SignalWindow -> Finding -> Similar Windows        |
+------------------------------------------------------------------------------------+
                                         |
                                         v
+------------------------------------------------------------------------------------+
|                      Evidence-Only LLM Orchestrator                                |
|        (Grounded Prompts, Zero Math Prompting, Structured Citations)               |
+------------------------------------------------------------------------------------+
                                         |
                                         v
+------------------------------------------------------------------------------------+
|                       FastAPI Endpoints / Conversational Chat                      |
+------------------------------------------------------------------------------------+
```

---

## Quickstart: How to Start the Project

### Prerequisites
- **Python 3.10+**
- **pip** package manager

### 1. Installation

Clone the repository and install the dependencies:

```bash
python3 -m pip install -r requirements.txt
```

### 2. Environment Configuration

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` to supply your API key (see [API Key Configuration](#api-key-configuration--headless-usage)).

### 3. Running the Servers

The project provides two FastAPI entrypoints depending on your workflow:

#### Option A: Conversational Frontend Server (`server.py`)
This is the recommended entrypoint for interactive chat and frontend integration. It automatically detects condition IDs and channels from user prompts, triggers background ingestion/analysis if needed, and returns status codes or grounded responses.

```bash
python3 -m uvicorn server:app --reload --port 8000
```

#### Option B: Low-Level Core API (`api/main.py`)
Provides direct access to explicit `/ingest`, `/profile`, `/analyse`, `/query`, and dynamic `/config` endpoints.

```bash
python3 -m uvicorn api.main:app --reload --port 8000
```

### 4. Running Verification & Regression Tests

Run the full synthetic regression suite:

```bash
python3 -m pytest -q
```

To run verification against a live mounted DAQ dataset:

```bash
DAQ_DATASET_ROOT=/path/to/Readngs_DAQ_Data DAQ_EXPECTED_FILE_COUNT=822 python3 -m pytest -q tests/test_manifest.py tests/test_quality.py
```

### 5. Training the Supervised Tool-Wear Regressor

Train the HistGradientBoosting tool-wear regressor model on real DAQ recordings and workbook targets:

```bash
python3 train_tool_wear_model.py --dataset-root dataset/Readngs_DAQ_Data --wear-workbook Tool_Wear_Value_Table.xlsx
```

---

## API Key Configuration & Headless Usage

Because no web frontend is required to operate the platform, you can fully interact with the system headlessly via API calls (`cURL`, Python `requests`, or Postman).

### 1. Setting Up `.env`

The platform supports both **Gemini** and **OpenAI** backends via the plugin registry.

#### Gemini Setup (Default)
Set the following in `.env`:

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_actual_gemini_api_key
GEMINI_MODEL=gemini-3.6-flash
GEMINI_MAX_RETRIES=2
```

> **Note**: `gemini-3.6-flash` is recommended for high-speed, reliable grounded reasoning. Retry logic handles transient HTTP 429/5xx capacity spikes with exponential backoff.

#### OpenAI Setup
Set the following in `.env`:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your_actual_openai_api_key
OPENAI_MODEL=gpt-6-astra
```

---

### 2. Interactive Headless Usage via API / cURL

#### A. Automatic Conversational Chat (`POST /chat`)

Send natural language questions directly to `server.py`. The server automatically extracts the target process condition (e.g. `condition 4`) and signal channel (e.g. `spindle vibration`), runs scope analysis in the background if necessary, and returns a grounded answer once ready.

**Request:**
```bash
curl -X POST "http://localhost:8000/chat" \
     -H "Content-Type: application/json" \
     -d '{
       "question": "What changed in spindle vibration for condition 4?"
     }'
```

**Response (Scope Analysis Pending - HTTP 202):**
```json
{
  "status": "analysing",
  "condition_id": "4",
  "channel": "Vib_Spindle",
  "message": "Analysing the requested signal. Retry this question when status is analysis_ready.",
  "status_url": "/chat/status"
}
```

**Check Status (`GET /chat/status`):**
```bash
curl http://localhost:8000/chat/status
# Returns: {"status": "analysis_ready"}
```

**Response (Scope Ready - HTTP 200):**
```json
{
  "answer": "For condition 4, spindle vibration exhibited significant energy departures from the normal process baseline across multiple sample windows. Low-frequency vibration energy departed most significantly [Finding 1].",
  "citations": [
    {
      "label": "Finding 1",
      "finding_id": "finding-0298a0f1",
      "model_version": "mahalanobis-diagonal-v3",
      "source_path": ".../N_4/Recording 12.csv",
      "channel": "Vib_Spindle",
      "window_id": "win-12-004",
      "sample_range": {"sample_start": 4096, "sample_end": 6144},
      "time_range": {"time_start": 0.4096, "time_end": 0.6144}
    }
  ],
  "finding_count": 1
}
```

---

#### B. Explicit Step-by-Step Direct API Calls (`api/main.py`)

If you prefer explicit control over each pipeline phase:

##### Step 1: Ingest and Profile the DAQ Dataset
```bash
curl -X POST "http://localhost:8000/ingest" \
     -H "Content-Type: application/json" \
     -d '{
       "folder_path": "dataset/Readngs_DAQ_Data",
       "config_path": "config/domain.yaml"
     }'
```

##### Step 2: Check Profiling Summary
```bash
curl http://localhost:8000/profile
```
*Returns inventory summary: total discovered recordings, canonical count, quarantined count, and rejection reason breakdown.*

##### Step 3: Trigger Scoped Signal Analytics
```bash
curl -X POST "http://localhost:8000/analyse" \
     -H "Content-Type: application/json" \
     -d '{
       "condition_id": "4",
       "channels": ["Vib_Spindle"],
       "window_size_samples": 2048,
       "overlap": 0.5,
       "anomaly_threshold": 3.0
     }'
```

##### Step 4: Check Analysis Status
```bash
curl http://localhost:8000/analyse/status
```

##### Step 5: Query Grounded Explanations
```bash
curl -X POST "http://localhost:8000/query" \
     -H "Content-Type: application/json" \
     -d '{
       "question": "Explain spindle vibration anomalies for condition 4",
       "filters": {
         "condition_id": "4",
         "channel": "Vib_Spindle"
       },
       "top_k": 3
     }'
```

##### Step 6: View or Hot-Reload Dynamic Configuration
```bash
# View active domain configuration
curl http://localhost:8000/config

# Hot-reload configuration without server restart
curl -X PUT "http://localhost:8000/config" \
     -H "Content-Type: application/json" \
     -d @config/domain.yaml
```

---

## What Results to Expect

### 1. Quality Gating & Inventory Profiling
- **Manifest Discovery**: Dynamic discovery of all `Recording <N>.csv` files organized under condition folders (`N_1`, `N_2`, ..., `N_25`).
- **Strict Quarantine Gating**: Input raw bytes undergo checksumming, NUL byte removal (`null_bytes_removed`), `surrogateescape` decoding, and column validation. Files with missing/malformed 7-channel numeric headers or mismatched sample widths are quarantined immediately with JSONL audit logs.
- **Profiling Results**: `/profile` reports exact canonical vs quarantined file breakdowns before heavy signal loading.

### 2. Signal Analytics & Baseline Anomaly Detection
- **Measured Sampling Rate ($f_s$)**: Calculated strictly from inverse median positive Time deltas. FFT frequency features (low/mid/high band energy, spectral centroid) are calculated **only** when $f_s$ is validated.
- **Per-Condition Baselines**: Baselines $(S, F, D)$ are calculated separately per condition and channel using only canonical recordings. Operating parameter changes (e.g. speed $S$, feed $F$, depth $D$) are never mistaken for defects.
- **Diagonal Mahalanobis Anomalies (v3)**: Evaluates distance against the condition baseline. Computes the top 3 feature departures and translates them into natural-language diagnostic facts.

### 3. Evidence-Grounded Conversational Explanations
- **Zero Math In LLM**: Prompt construction feeds pre-calculated diagnostic statements to the LLM.
- **Clear Citations**: Answers include clean inline markers (`[Finding 1]`) along with full JSON citations containing source CSV paths, channel names, sample indices, and physical timestamps.

### 4. Supervised Tool-Wear Regression
- **Target Integration**: Joins computed DAQ features with actual tool wear measurements ($\mu m$) from `Tool_Wear_Value_Table.xlsx`.
- **Model Evaluation**: Evaluates HistGradientBoosting regression using whole-recording train/test splits (zero window leakage). Exports `model.joblib` and `evaluation.json` detailing Mean Absolute Error (MAE), Root Mean Squared Error (RMSE), and $R^2$ score.

### 5. Persistent Local Caching
- **Fingerprinted Cache**: Manifest signatures (file size, modification time, config hash) and analysis settings are cached under `runtime/daq_cache/`.
- **Fast Restores**: Re-running ingestion or scope analysis on identical data restores state in milliseconds without re-reading 41 GB of raw CSV files.

---

## Repository & Module Structure

### Directory Tree

```
institutional-memory/
├── .env.example                  # Environment configuration template
├── README.md                     # Project documentation & user guide
├── KNOWLEDGE_BASE.md             # In-depth architectural blueprint
├── progress.md                   # Implementation step log & verification checklist
├── requirements.txt              # Python dependencies
├── server.py                     # Frontend-facing conversational chat entrypoint
├── build_kg.py                   # Knowledge graph construction utility script
├── train_tool_wear_model.py      # Supervised tool-wear training pipeline
├── golden_test_suite.py          # Synthetic golden test evaluation runner
├── evaluate_qwen.py              # Local LLM evaluation suite script
├── analytics/                    # Feature baselining, anomaly detection & tool wear
│   ├── anomaly.py                # Diagonal Mahalanobis detector (v3) with feature departures
│   ├── baselines.py              # Per-condition normal feature baseline profiles
│   ├── evaluation.py             # Leakage-safe whole-condition / recording splitters
│   └── tool_wear.py              # Supervised tool-wear regressor dataset & model pipeline
├── api/                          # REST API layer
│   └── main.py                   # Core FastAPI application & background job orchestrator
├── config/                       # Domain settings
│   └── domain.yaml               # Domain configuration schema, channels & limits
├── core/                         # Core system contracts & registry
│   ├── config.py                 # YAML config loader & runtime hot-reloader
│   ├── registry.py               # Plugin registries for Parsers, Embedders, Vector/Graph, LLMs
│   └── schema.py                 # Unified Pydantic models (Recording, SignalWindow, Finding, etc.)
├── ingestion/                    # DAQ data ingestion & quality gates
│   ├── manifest.py               # Dataset discovery & manifest compilation
│   ├── quality.py                # Raw byte checksums, NUL removal & CSV validation gates
│   ├── pipeline.py               # DAQ ingestion pipeline orchestrator
│   ├── chunker.py                # Document chunking strategies (text/RAG)
│   └── parsers/                  # Format-specific parsers
│       ├── csv_daq_parser.py     # DAQ CSV quality profiling & full numeric loading
│       ├── pdf_parser.py         # PDF document text parser
│       ├── cad_parser.py         # CAD file metadata parser
│       └── email_parser.py       # E-mail message parser
├── knowledge/                    # Graph ontology & entity resolution
│   ├── ontology.py               # Typed DAQ lineage graph builder (Condition->Recording->Window->Finding)
│   ├── graph_store.py            # In-memory Neo4j graph driver simulator
│   └── ner.py                    # Entity extraction & alias table resolution
├── llm/                          # LLM explanation & prompt engineering
│   ├── orchestrator.py           # Grounded explanation orchestrators (DAQ & RAG)
│   └── prompt_builder.py         # Zero-computation prompt formatting & templates
├── retrieval/                    # Signal & document retrieval
│   ├── metadata_index.py         # Fast metadata index for exact DAQ condition/channel filtering
│   ├── feature_store.py          # Dense vector store for signal feature vectors
│   ├── retriever.py              # DAQ hybrid retriever (Metadata -> Feature Store -> Graph)
│   ├── vector_store.py           # In-memory text chunk vector store
│   └── embedder.py               # Text embedding registry implementations
├── runtime/                      # Derived local runtime cache (git-ignored)
│   └── daq_cache/                # Fingerprinted ingest & analysis cache files
└── tests/                        # Comprehensive synthetic test suite
    ├── test_manifest.py          # Manifest discovery unit tests
    ├── test_quality.py           # Quality gate & sanitization unit tests
    ├── test_daq_pipeline.py      # Pipeline orchestration unit tests
    ├── test_signal.py            # Preprocessing & sampling rate unit tests
    ├── test_features.py          # Feature extraction unit tests
    ├── test_baselines.py         # Condition baseline unit tests
    ├── test_anomaly.py           # Anomaly detection unit tests
    ├── test_evaluation.py        # Leakage-safe split unit tests
    ├── test_ontology.py          # Graph lineage unit tests
    ├── test_daq_retrieval.py     # Hybrid retrieval unit tests
    ├── test_daq_orchestrator.py   # Grounded LLM explanation unit tests
    └── test_daq_api.py           # End-to-end API integration tests
```

---

### Module Responsibilities

| Module / Path | Main Responsibility |
|---|---|
| **`server.py`** | High-level conversational chat API (`POST /chat`, `GET /chat/status`). Extracts condition/channel scope from queries and triggers automatic background ingestion and analysis. |
| **`api/main.py`** | Primary FastAPI service exposing low-level endpoints (`/ingest`, `/profile`, `/analyse`, `/query`, `/config`). Controls async worker threads, dataset fingerprinting, and state caching. |
| **`ingestion/manifest.py`** | Discovers CSV recordings under condition folders, extracting $S, F, D$ operating parameters without parsing CSV contents. |
| **`ingestion/quality.py`** | Enforces quality gates: checksums, NUL byte stripping, field-size limit overrides, column counts, and numeric validation before data enters the pipeline. |
| **`ingestion/parsers/csv_daq_parser.py`** | Profiles CSV files into canonical or quarantined statuses, generating JSONL rejection logs and parsing numeric arrays. |
| **`signal/preprocessing.py`** | Derives sampling frequency ($f_s$) from strictly positive time deltas and performs single-pass channel NaN linear interpolation. |
| **`signal/windowing.py`** | Slices continuous channels into fixed 2048-sample windows with 50% overlap, maintaining exact sample index boundaries and timestamps. |
| **`signal/features.py`** | Computes 9 time-domain metrics (mean, std, RMS, crest factor, kurtosis, skewness) and FFT frequency band energies (low, mid, high) gated on valid $f_s$. |
| **`analytics/baselines.py`** | Fits normal reference profiles per `(condition_id, channel)` from canonical recordings only. |
| **`analytics/anomaly.py`** | Scores window departures using diagonal Mahalanobis distance ($v3$), extracting top feature departures and plain-language evidence. |
| **`analytics/tool_wear.py`** | Joins DAQ diagnostic features with workbook tool wear measurements to train and evaluate a HistGradientBoosting regressor. |
| **`knowledge/ontology.py`** | Constructs typed graph lineage: `Condition` $\rightarrow$ `Recording` $\rightarrow$ `SignalWindow` $\rightarrow$ `Finding`. |
| **`retrieval/metadata_index.py`** | Provides exact key-value indexing over condition IDs, channels, and recording metadata. |
| **`retrieval/feature_store.py`** | Stores dense window feature vectors and supports nearest-neighbor cosine/Euclidean similarity searches. |
| **`retrieval/retriever.py`** | Orchestrates hybrid DAQ retrieval: metadata filter candidates $\rightarrow$ vector feature ranking $\rightarrow$ graph neighborhood context. |
| **`llm/orchestrator.py`** | Formulates grounded prompts, enforces zero-computation rules, invokes Gemini/OpenAI models, and builds structured citations. |
| **`core/registry.py`** | Provides pluggable registries for dynamic swapping of Parsers, Embedders, Vector Stores, Graph Stores, and LLM backends. |
| **`core/config.py`** | Loads `domain.yaml` settings and enables runtime hot-reloading without server restarts (`PUT /config`). |

---

## Future Plans & Roadmap

1. **Interactive Web Dashboard (React / Next.js)**:
   - Visual waveform viewer with interactive window overlay and anomaly highlight heatmaps.
   - Real-time conversational interface connected to `POST /chat`.
2. **Real-Time Stream Processing**:
   - WebSockets and Kafka/MQTT streaming ingestion for online anomaly detection on live CNC machinery.
3. **Advanced Machine Learning Models**:
   - 1D-CNN and Autoencoder models for complex multimodal signal anomaly detection.
   - Multi-step Remaining Useful Life (RUL) forecasting for cutting tools.
4. **Distributed Scale-Out Execution**:
   - Integration with PySpark / Dask for distributed window feature computation across terabyte-scale DAQ datasets.
5. **Multi-Modal Document & Sensor Fusion**:
   - Seamless cross-retrieval linking machine maintenance PDF manuals and CAD drawings directly with signal anomaly findings.

