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
