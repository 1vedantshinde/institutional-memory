# institutional-memory
An Industrial Knowledge Intelligence Platform

## Enable real chatbot answers

The DAQ pipeline computes and retrieves evidence locally. A real LLM only
explains those retrieved facts; it never receives raw signal arrays or performs
signal calculations. The default local provider is a test mock, and `/query`
returns HTTP 503 instead of presenting a fake answer while it is active.

Install dependencies and configure the provider before starting the API:

```bash
python3 -m pip install -r requirements.txt
export LLM_PROVIDER=openai
export OPENAI_API_KEY='your_api_key'
export OPENAI_MODEL='gpt-6-astra'
python3 -m uvicorn api.main:app --reload
```

Keep the API key out of Git; `.env` is ignored. The official OpenAI SDK reads
`OPENAI_API_KEY` from the process environment.

## Frontend chatbot server

Start the frontend-facing server with:

```bash
python3 -m uvicorn server:app --reload
```

Your frontend sends only a question to `POST /chat`. The server detects an
explicit condition and signal channel, automatically loads a cached analysis or
starts scoped analytics, and then returns the evidence-grounded answer. For a
new scope it returns HTTP 202 with `status: analysing`; poll `GET /chat/status`
and resend the same question once it returns `analysis_ready`.

```json
{"question":"What changed in spindle vibration for condition 4?"}
```

For immediate answers after a server restart, keep the local analysis cache.
The first request for a never-analysed condition/channel must complete signal
analytics before an answer is allowed.
