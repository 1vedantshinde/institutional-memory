# Institutional Memory
**An Industrial Knowledge Intelligence Platform**

A decoupled, format-agnostic RAG (Retrieval-Augmented Generation) backend for industrial environments — designed to ingest heterogeneous document formats, extract and store a knowledge graph, perform hybrid retrieval, and generate grounded answers from a pluggable LLM.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Project Structure](#project-structure)
- [Setup](#setup)
- [Environment Variables](#environment-variables)
- [Running the API](#running-the-api)
- [API Endpoints](#api-endpoints)
- [Running with Real Infrastructure](#running-with-real-infrastructure)
- [Evaluation Harness](#evaluation-harness)
- [Changelog — Implementation Notes](#changelog--implementation-notes)

---

## Architecture Overview

```
                  ┌─────────────┐
  Raw Files ────► │  Parsers    │  PDF · DXF/CAD · Email · Python
                  └──────┬──────┘
                         │ UnifiedDocument
                  ┌──────▼──────┐
                  │   Chunker   │  Sentence / Code / Semantic
                  └──────┬──────┘
                         │ Chunks + Embeddings
          ┌──────────────┼──────────────┐
          │              │              │
   ┌──────▼──────┐  ┌────▼────┐  ┌─────▼──────┐
   │ Vector Store│  │  NER /  │  │   Graph    │
   │  (Qdrant)   │  │  RAKG   │  │  (Neo4j)   │
   └──────┬──────┘  └────┬────┘  └─────┬──────┘
          │              │              │
          └──────────────┼──────────────┘
                         │
                  ┌──────▼──────┐
                  │   Hybrid    │  BM25 + Vector (weighted RRF)
                  │  Retriever  │  + Query Router + Cross-Encoder
                  └──────┬──────┘
                         │ + Graph Augmentation (PathRAG-style)
                  ┌──────▼──────┐
                  │     LLM     │  Mock · Anthropic (pluggable)
                  └──────┬──────┘
                         │ Grounded Answer + Citations + Confidence
                  ┌──────▼──────┐
                  │  FastAPI    │  REST API with auth + .env
                  └─────────────┘
```

---

## Project Structure

```
.
├── api/
│   └── main.py                  # FastAPI entrypoint — auth, ingest, query, config
├── core/
│   ├── config.py                # Domain YAML loader + hot-reload
│   ├── registry.py              # Plugin registry — parsers, embedders, stores, LLMs
│   └── schema.py                # Pydantic schemas: UnifiedDocument, Chunk, Node, Edge
├── ingestion/
│   ├── chunker.py               # Sentence / code / semantic chunking strategies
│   ├── pipeline.py              # Ingest orchestrator — parse → chunk → embed → graph
│   └── parsers/
│       ├── pdf_parser.py        # Real pypdf parser with fallback
│       ├── cad_parser.py        # DXF/AutoCAD parser (ezdxf)
│       ├── email_parser.py      # .eml / .mbox / .msg parser
│       └── code_parser.py       # Python source parser
├── knowledge/
│   ├── graph_store.py           # Neo4j real driver + in-memory simulation (auto-select)
│   └── ner.py                   # Hybrid NER: regex tags + RAKG entity resolution
├── retrieval/
│   ├── embedder.py              # DeterministicEmbedder (mock) + PluggableEmbedder (neural)
│   ├── vector_store.py          # QdrantRealClient + QdrantMockClient (auto-select)
│   ├── retriever.py             # BM25 + Vector + weighted RRF + cross-encoder + graph_augment
│   └── router.py                # Query router: LOOKUP / PROCEDURAL / SEMANTIC
├── llm/
│   ├── orchestrator.py          # RAG orchestrator — confidence scoring, citation mapping
│   ├── providers.py             # Real LLM providers (Anthropic)
│   └── prompt_builder.py        # Domain-aware prompt construction
├── eval/
│   ├── golden_set.json          # Golden query set for regression testing
│   └── run_eval.py              # Eval harness — Recall@8, routing, end-to-end confidence
├── config/
│   └── domain.yaml              # Active domain ontology (entity types, relation types, glossary)
├── docker-compose.yml           # Qdrant + Neo4j services with named volumes
├── .env.example                 # Environment variable template
└── requirements.txt
```

---

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/1vedantshinde/institutional-memory.git
cd institutional-memory
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — at minimum set LLM_PROVIDER and any backend URLs you want to use
```

### 3. (Optional) Start real infrastructure

```bash
docker compose up -d   # starts Qdrant on :6333 and Neo4j on :7474 / :7687
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `mock` | LLM backend: `mock` or `anthropic` |
| `ANTHROPIC_API_KEY` | — | Required when `LLM_PROVIDER=anthropic` |
| `USE_NEURAL_MODELS` | `0` | Set to `1` to use `all-MiniLM-L6-v2` embeddings |
| `EMBEDDING_DIM` | `1536` | Set to `384` when `USE_NEURAL_MODELS=1` (re-ingest required) |
| `QDRANT_URL` | *(empty)* | Set to `http://localhost:6333` to activate real Qdrant |
| `NEO4J_URI` | *(empty)* | Set to `bolt://localhost:7687` to activate real Neo4j |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | `testpassword` | Neo4j password |
| `API_KEY` | *(empty)* | When set, enforces `X-API-Key` header on write endpoints |

> **Note:** Leaving `QDRANT_URL` and `NEO4J_URI` empty uses safe in-memory mocks — no Docker required for local dev.

---

## Running the API

```bash
uvicorn api.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

---

## API Endpoints

| Method | Endpoint | Auth Required | Description |
|---|---|---|---|
| `POST` | `/ingest` | ✅ | Upload and ingest a single document |
| `POST` | `/ingest-folder` | ✅ | Ingest all supported docs in a directory |
| `POST` | `/ingest/graph` | ✅ | Directly inject validated Node/Edge graph elements |
| `POST` | `/query` | ❌ | Hybrid retrieval + LLM answer + citations |
| `GET` | `/config` | ❌ | Get active domain configuration |
| `PUT` | `/config` | ✅ | Hot-reload domain ontology without restart |

> Auth endpoints require `X-API-Key: <your_key>` header when `API_KEY` env var is set.

### Example: Ingest a document

```bash
curl -X POST http://localhost:8000/ingest \
  -H "X-API-Key: your_api_key" \
  -F "file=@/path/to/sop_document.pdf"
```

### Example: Query

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What should be done if Pump-101 fails?", "limit": 8}'
```

**Response:**
```json
{
  "query": "What should be done if Pump-101 fails?",
  "answer": "...",
  "citations": [{"chunk_id": "...", "doc_id": "...", "snippet": "..."}],
  "confidence": 0.74
}
```

---

## Running with Real Infrastructure

### Real LLM (Anthropic Claude)

```bash
export LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...
```

### Real Embeddings (all-MiniLM-L6-v2)

```bash
# One-time model download
python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Then activate
export USE_NEURAL_MODELS=1
export EMBEDDING_DIM=384
# ⚠️  Re-ingest all documents after changing EMBEDDING_DIM — vectors are incompatible across dimensions
```

### Real Qdrant + Neo4j

```bash
docker compose up -d

export QDRANT_URL=http://localhost:6333
export NEO4J_URI=bolt://localhost:7687
export NEO4J_PASSWORD=testpassword
```

Verify Qdrant: `curl localhost:6333/collections`
Verify Neo4j: open `http://localhost:7474` → run `MATCH (n) RETURN n`

---

## Evaluation Harness

Run the eval harness after any significant change (embedder swap, LLM change, prompt edit):

```bash
python3 eval/run_eval.py
```

**Output:**
- **Recall@8** — fraction of golden queries where expected documents appear in the top-8 results
- **Query routing** — classification of each query (LOOKUP / PROCEDURAL / SEMANTIC)
- **End-to-end results** — confidence score and citation count per query
- Exits with code `1` if >30% of queries fail the confidence bar (use as CI gate)

Populate `eval/golden_set.json` with real `expected_doc_ids` from your corpus after the first ingestion run.

---

## Changelog — Implementation Notes

### Steps 1–7 (Core Fixes)

| Step | File | Change |
|---|---|---|
| **1** | `core/registry.py` | `InMemoryGraphStore` delegates to shared `Neo4jSimulationDriver` singleton — ingestion writes now visible to query-time `graph_augment()` |
| **2** | `ingestion/pipeline.py` | `ingest_file()` auto-calls NER and populates knowledge graph on every document ingestion |
| **3** | `ingestion/parsers/cad_parser.py` | Fixed DXF crash: `ezdxf.readstring()` → `ezdxf.read(io.StringIO(...))` |
| **4** | `llm/orchestrator.py` | Removed fake `0.95` confidence shortcut for mock LLM |
| **5** | `llm/orchestrator.py` | Citation mapping now only trusts explicit `[chunk_id]` bracket tags — removed loose keyword-overlap fallback |
| **6** | `ingestion/parsers/code_parser.py` *(new)* | `PythonParser` registered as a real module — `.py` uploads no longer 500 |
| **7** | `retrieval/embedder.py`, `retrieval/vector_store.py` | `mock` key always returns deterministic vectors; vector search fetches 5× limit when filters are active |

### Phase A — Real Infrastructure Swaps

| Phase | File | Change |
|---|---|---|
| **A1** | `llm/providers.py` *(new)*, `llm/orchestrator.py` | `AnthropicLLM` backend — toggle via `LLM_PROVIDER` env var |
| **A4** | `ingestion/parsers/pdf_parser.py` | Real `pypdf.PdfReader` with UTF-8 fallback for test bytes |
| **A5** | `retrieval/vector_store.py` | `QdrantRealClient` auto-selected via `QDRANT_URL`; `list_all_points()` on both mock and real |
| **A6** | `knowledge/graph_store.py` | `Neo4jRealDriver` auto-selected via `NEO4J_URI`; identical interface to simulation driver |

### Phase B — Features

| Phase | File | Change |
|---|---|---|
| **B1** | `retrieval/router.py` *(new)*, `retrieval/retriever.py` | Rule-based query router (LOOKUP / PROCEDURAL / SEMANTIC) with per-route BM25/vector weights fed into weighted RRF |
| **B2** | `eval/golden_set.json` *(new)*, `eval/run_eval.py` *(new)* | Eval harness: Recall@8, routing classification, end-to-end confidence, CI-ready exit code |
| **B3** | `retrieval/retriever.py` | `graph_augment()` scores 1-hop triplets by query-token overlap and keeps top 5 (PathRAG-style pruning) |

### Phase C — Production Hardening

| Phase | File | Change |
|---|---|---|
| **C1** | `docker-compose.yml` | Full Qdrant + Neo4j services with named Docker volumes |
| **C2** | `.env.example`, `requirements.txt` | All deps documented; `python-dotenv` loads `.env` at API startup; `.env` in `.gitignore` |
| **C3** | `api/main.py` | `ingest_file()` returns structured `{status, stage, error}` dicts — batch ingest never aborts on partial failure |
| **C4** | `api/main.py` | `X-API-Key` header enforcement on all write endpoints via FastAPI `Depends` |

---

## Supported Document Formats

| Extension | Parser | Modality |
|---|---|---|
| `.pdf` | `PDFParser` (pypdf) | `text` |
| `.dxf` | `CADParser` (ezdxf) | `cad` |
| `.eml`, `.mbox`, `.msg` | `EmailParser` | `email` |
| `.py` | `PythonParser` | `code` |

---

## Domain Configuration

Edit `config/domain.yaml` to define your ontology — entity types, relation types, glossary terms, and entity aliases. Changes take effect immediately via `PUT /config` (no restart required).

```yaml
domain_name: "Generic Industrial Plant"
entity_types:
  - Equipment
  - Procedure
  - Incident
relation_types:
  - MAINTAINED_BY
  - CAUSED_BY
  - MENTIONED_IN
glossary:
  - term: SOP
    meaning: Standard Operating Procedure
```
