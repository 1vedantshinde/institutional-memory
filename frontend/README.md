# Institutional Memory — DAQ Condition Intelligence

React + TypeScript + Vite frontend for the CNC-machining sensor anomaly intelligence platform.

## Quick start

```bash
pnpm install            # or: npm install
cp .env.example .env.local
```

`.env.example` lists every variable the app reads, with its default. `.env.local`
also drives the dev-server port (`PORT`, default 5173) and the `/chat-api` and
`/core-api` proxy targets.

### Run with mock backend (no real backend needed)

```bash
# First, initialize the MSW service worker
npx msw init public/ --save

VITE_USE_MOCKS=true pnpm dev
```

All pages work fully with mocks. The chat flow simulates 202→poll→200, the dataset health page shows sample quarantine data, and the analysis page completes after two polls.

### Run against real backends

```bash
# Terminal 1 — chat server
python3 -m uvicorn server:app --reload --port 8000

# Terminal 2 — core API
python3 -m uvicorn api.main:app --reload --port 8001

# Terminal 3 — frontend
pnpm dev
```

The frontend defaults to `http://localhost:8000` (chat) and `http://localhost:8001` (core). Change URLs at runtime in the **Settings** drawer (top-right gear icon); they persist in `localStorage`.

## How to swap API URLs

**Option 1 — Settings drawer (runtime)**
Click the gear icon in the top bar. Paste new URLs and click Save. Changes persist across page reloads.

**Option 2 — Environment variables**
```bash
VITE_CHAT_API_URL=http://my-server:8000 \
VITE_CORE_API_URL=http://my-server:8001 \
pnpm dev
```

**Option 3 — Vite dev proxy (avoids CORS)**
The dev server proxies `/chat-api/*` → `VITE_CHAT_API_URL` and `/core-api/*` → `VITE_CORE_API_URL`. If you see CORS errors, either:
- Add `CORSMiddleware` to both backends allowing `http://localhost:5173` (or whatever `$PORT` the frontend runs on), or
- Change your API client base URLs to use the proxy paths.

## Running tests

```bash
pnpm test:run      # run once
pnpm test          # watch mode
pnpm coverage      # with coverage report
```

Tests run against the MSW handlers in `src/mocks/handlers.ts` (wired up in `src/test/setup.ts`; any request without a handler fails the test rather than reaching the network):

- `useChatFlow` state machine — 200, 202→poll→auto-resend→200, 503, network failure, cancel, retry
- `postChat` — 202/200 sequence, 503, non-JSON 503 body, connection failure → `NetworkError`
- Dataset Health — ingest→poll `/profile`→KPIs/reasons, alternate profile key names, 400 path message
- Analysis — analyse→poll→complete→"Ask about this scope" handoff, failure state, second run not reusing a stale status
- Config — diff dialog (added/removed/changed), PUT only after confirm, cancel, non-object/invalid JSON rejected, no-op save disabled, server error inline

## Preview pages (proposed endpoints)

```bash
VITE_ENABLE_PROPOSED=true VITE_USE_MOCKS=true pnpm dev
```

Reveals **Waveforms & Findings** and **Tool Wear** pages. Both display a "Preview — backend endpoint not implemented yet" banner. See `BACKEND_REQUESTS.md` for the proposed API spec.

## Known backend gaps

See `BACKEND_REQUESTS.md`. The following endpoints are not yet implemented and are only available in MSW mock mode:

- `GET /conditions` — list all 25 process conditions
- `GET /findings` — query indexed anomaly findings
- `GET /recordings/{id}/windows/{window_id}/signal` — waveform data for preview
- `GET /tool-wear/evaluation` — evaluation metrics from the offline training script

## Project structure

```
src/
  api/            Typed fetch clients, Zod schemas, defensive normalizers, proposed endpoint types
  mocks/          MSW handlers and fixtures
  features/ask/   Chat UI components + useChatFlow state machine
  features/...    Per-page feature components
  pages/          Route-level page components
  components/     Shared UI (shadcn-style primitives, Layout, Sidebar, TopBar)
  lib/            Pure utilities (channels, path parsing, citation parsing, formatting)
  store/          Reactive session store (chat messages, evidence, settings)
```

## Core principle

> The AI explains; it never calculates.

All numbers — Mahalanobis distances, sample ranges, window IDs, time boundaries — are computed by deterministic Python analytics. The LLM reads those findings and generates grounded natural-language explanations with `[Finding N]` markers that link to structured citations.
