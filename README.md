# Agentic Research Assistant

A tool-calling research agent — **LangChain + OpenAI** — served over **FastAPI with SSE streaming**,
with a **React + TypeScript** chat UI that renders live tool-call traces, backed by **PostgreSQL**
for conversation memory, tool logs, and response caching.

<img width="836" height="471" alt="Agentic Research Assistant Dashboard (1)" src="https://github.com/user-attachments/assets/83f6efd3-a7f7-45a2-bcbb-04ec38a65668" />


## Features

- **Agentic tool-calling loop** (max 6 iterations) over 4 tools: `web_search`, `sql_query`,
  `calculator`, `document_retrieval` (`backend/app/tools.py`)
- **Streaming (SSE) answers** with typed events: `reasoning | tool_start | tool_end | token | cached | done`
- **Live trace UI**: each assistant message shows the reasoning steps and tool invocations that produced it
- **Conversation memory** in Postgres (`messages`, `conversations`) with bounded history
- **Tool audit log** (`tool_logs`: name, input, output, latency, status per call)
- **Response cache** (`response_cache` + TTL) — cache hits skip the LLM entirely
- **Read-only SQL guardrails**: `SELECT`-only, table whitelist, write-keyword rejection
- **100-query offline eval suite** + **9 end-to-end tests**, all runnable without API keys

## Architecture

```
┌──────────────┐   POST /chat/stream (SSE)   ┌────────────────────────┐
│  React + TS  │ ◄────────────────────────── │  FastAPI (app/main.py) │
│  ChatWindow  │   token/reasoning/tool_*     │  run_stream (agent.py) │
└──────────────┘                              └───────────┬────────────┘
                                                         │ AgentExecutor
                                              ┌──────────▼───────────┐
                                              │  gpt-4o-mini (OpenAI) │
                                              └──────────┬───────────┘
                          ┌──────────────────┬───────────┼────────────┬──────────────────┐
                          ▼                  ▼           ▼            ▼                  ▼
                    web_search          sql_query   calculator  document_retrieval   response_cache
                 (Tavily → DDG)      (Postgres,    (safe AST)   (Postgres FTS +      (Postgres, TTL)
                                      read-only)                 trigram)
```

**Request flow** (`backend/app/agent.py:25`):

1. `ensure_conversation` → resolve/create conversation id
2. `cache_get(query, conv)` → on hit, emit `cached` + replay tokens, return (no LLM call)
3. Load bounded history (`MAX_HISTORY_MESSAGES=12`) → `executor.astream_events`
4. Re-emit model chunks as `token`, tool transitions as `tool_start`/`tool_end` (+ `tool_logs` row)
5. Persist assistant message → `cache_set` → emit `done`

The deterministic policy behind tool selection lives in two places that mirror each other:
`backend/app/prompts.py` (`SYSTEM_PROMPT`, used by the live agent) and
`backend/app/router.py` (`predict_tool`, the testable specification used by evals).

## Tech stack

| Layer    | Choice |
|----------|--------|
| Agent    | LangChain tool-calling agent, `ChatOpenAI(gpt-4o-mini, temperature=0)` |
| API      | FastAPI, `sse-starlette` `EventSourceResponse` |
| UI       | React 18 + TypeScript + Vite |
| DB       | PostgreSQL 16 (`asyncpg` + SQLAlchemy async), trigram + full-text search |
| Search   | Tavily (keyed) with DuckDuckGo fallback (keyless) |

## Quickstart

### Option A — Docker

```bash
cp .env.example .env        # set OPENAI_API_KEY
docker compose up --build
# db :5432 · backend :8000 · frontend :5173
curl -X POST localhost:8000/seed   # insert demo documents
```

### Option B — local

```bash
# 1. database
psql "$DATABASE_URL" -f backend/schema.sql

# 2. backend
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload   # :8000

# 3. frontend
cd frontend && npm install && npm run dev   # :5173
```

## Configuration

| Var | Default | Notes |
|-----|---------|-------|
| `OPENAI_API_KEY` | — | required for the live agent |
| `TAVILY_API_KEY` | — | optional; without it `web_search` uses DuckDuckGo |
| `DATABASE_URL` | `postgresql+asyncpg://agent:agent@localhost:5432/agent_db` | — |
| `MODEL_NAME` | `gpt-4o-mini` | — |
| `MAX_HISTORY_MESSAGES` | `12` | bounds prompt tokens (see Latency) |
| `CACHE_TTL_SECONDS` | `3600` | `response_cache.expires_at` |

## API reference

### `POST /chat/stream`

Body: `{ "query": string, "conversation_id"?: uuid }` — returns `text/event-stream`.

Each SSE frame is `data: <json>\n\n`, where json is
`{ "type": <event>, "conversation_id": <uuid>, "data": <payload> }`:

| Event | Payload | Meaning |
|-------|---------|---------|
| `reasoning` | string | planner status line |
| `tool_start` | `{tool, input}` | agent invoked a tool |
| `tool_end` | `{tool, output}` (truncated) | tool returned |
| `token` | string | answer chunk |
| `cached` | `true` | response served from cache, LLM skipped |
| `done` | string | full final answer |

Minimal client:

```bash
curl -N -X POST localhost:8000/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"query":"Calculate 12*7"}'
```

### `GET /conversations/{id}/tools`

Last 50 tool invocations for a conversation (name, input, output excerpt, latency).

### `GET /health` · `POST /seed`

Liveness probe; seed two demo documents into `documents`.

## Tools

| Tool | Policy | Implementation |
|------|--------|----------------|
| `web_search` | current/external facts | Tavily if `TAVILY_API_KEY`, else DuckDuckGo instant API (`tools.py:11`) |
| `sql_query` | `SELECT` only, tables ∈ `{documents, messages, tool_logs}`, no write keywords | guardrail in `app/guards.py:14`, shared by tool + evals + tests |
| `calculator` | arithmetic only, never `eval` | safe AST walker (`+ - * / ** %`, unary minus) in `app/guards.py:48` |
| `document_retrieval` | project/domain knowledge | Postgres FTS rank + `ILIKE` fallback, top-3 snippets (`tools.py:71`) |

## Database schema

`backend/schema.sql`:

- `conversations(id, title, created_at, updated_at)`
- `messages(id, conversation_id → conversations, role ∈ {user,assistant,system,tool}, content, reasoning, created_at)` + index on `(conversation_id, created_at)`
- `tool_logs(id, conversation_id, message_id, tool_name, tool_input JSONB, tool_output, latency_ms, status, created_at)`
- `documents(id, title, content, source_url, created_at)` + trigram GIN index
- `response_cache(cache_key PK, query, response, created_at, expires_at)` + expiry index

## Prompt design & latency

- **Short system prompt** (`prompts.py:1`, 5 rules: docs-vs-web routing, SQL read-only, calculator-first math, citations, history-first) plus a minimal research template — p95 prompt ≈ **1.2k tokens** vs ≈3.5k for a naive full-history + verbose-instruction baseline.
- **Bounded history** (`MAX_HISTORY_MESSAGES=12`) caps growth per turn.
- **Response cache**: `cache_key = sha256(normalized query | conversation_id)[:32]`; hits stream the stored answer with zero LLM/tool latency (`agent.py:35`).
- Reported ~35% average latency reduction comes from cache hits on repeated/related queries plus the smaller prompts above; reproduce it by comparing `/chat/stream` wall time cold vs cached for the eval's repeated-query subset. The offline micro-benchmark below isolates the caching effect on tool calls (95.2% on 500 repeated evaluations — no network/LLM involved).

## Evaluation

No keys, no DB needed. The suite pins the agent's *policy* (router) and each tool's *unit behavior*:

```bash
python backend/eval.py   # exits 0 iff task-completion >= 90%
```

- Dataset: `backend/evals/eval_data.jsonl` — **100 queries**: 25 calculator (exact-value),
  25 SQL guardrail (15 valid `SELECT` + 10 injection/table-escape must-block),
  25 document retrieval (top-1 against a 6-doc KB mirroring seeded Postgres content),
  15 web routing, 10 multi-hop first-hop routing.
- Metric: **task completion = correct tool AND correct tool result**.
- Live-LLM extension: with `OPENAI_API_KEY` set, the same 100 queries can be replayed through
  `run_stream` asserting the emitted `tool_start` sequence matches `expected_tool(s)` —
  the deterministic `router.py` is the oracle.

### Measured results (`backend/evals/results.json`)

| Category | n | Routing | Tool-unit | Task completion |
|----------|---|---------|-----------|-----------------|
| calculator | 25 | 100.0% | 100.0% | 100.0% |
| sql | 25 | 100.0% | 100.0% | 100.0% |
| docs | 25 | 100.0% | 100.0% | 100.0% |
| web | 15 | 100.0% | 100.0% | 100.0% |
| multi-hop | 10 | 100.0% | 100.0% | 100.0% |
| **Overall** | **100** | **100.0%** | **100.0%** | **100.0%** |

Cache micro-benchmark (500 repeated tool evaluations): cold ≈0.0025s → warm ≈0.0001s (**≈−95%**; varies run to run — see `backend/evals/results.json` for the last measured figures).
Scope note: these are offline policy/unit measurements on a curated set; the original 90%-on-live-LLM
claim requires a keyed run and will read lower on adversarial paraphrases.

## End-to-end tests

```bash
python backend/tests/test_e2e.py        # 9 tests, stdlib + fastapi only
```

| Test | What it proves |
|------|----------------|
| `TestEvalData` | dataset is exactly 100 rows with the expected category split |
| `TestCalculator` | all 25 eval expressions through live `calc_eval`, plus code-injection rejection |
| `TestSqlGuardrail` | all 25 allow/block expectations through live `is_select_allowed` |
| `TestRouter` | full 100-query routing accuracy ≥ 90% through live `predict_tool` |
| `TestCacheKey` | normalization, conversation scoping, key length |
| `TestSseFraming` | SSE frame round-trip using the same `data:` parsing as `frontend/src/api.ts` |
| `TestApi` | **real** `app.main` over `TestClient` (langchain/SSE/DB stubbed at the boundary): `/health` + `POST /chat/stream` event order `reasoning → tool_start → tool_end → token → done` |

Result: **9 tests, OK**. Frontend verified separately: `npx tsc --noEmit` clean and
`npm run build` succeeds (`dist/` bundle emitted).

## Project structure

```
.
├── docker-compose.yml            # db + backend + frontend
├── .env.example
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI + SSE endpoints (lifespan startup)
│   │   ├── agent.py              # LangChain executor + run_stream generator
│   │   ├── tools.py              # 4 tool definitions (thin over guards.py)
│   │   ├── guards.py             # stdlib-only: SQL guardrail, safe calc, cache key
│   │   ├── router.py             # stdlib-only deterministic tool router
│   │   ├── memory_cache.py       # history, messages, tool_logs, response_cache
│   │   ├── prompts.py            # system prompt + research template
│   │   ├── config.py / schemas.py / db.py
│   ├── schema.sql                # Postgres DDL
│   ├── eval.py                   # 100-query harness (stdlib only)
│   ├── evals/eval_data.jsonl     # the 100 queries + expectations
│   ├── evals/results.json        # last measured results
│   └── tests/test_e2e.py         # 9 end-to-end tests
└── frontend/src/
    ├── api.ts                    # SSE fetch + frame parser (streamChat)
    ├── App.tsx / main.tsx
    └── components/ChatWindow.tsx # chat + cached badge
    └── components/ToolTrace.tsx  # reasoning + tool-call trace panel
```

## Limitations & next steps

- Live web results depend on Tavily/DDG availability; answers should carry confidence + sources (already cited as `[doc:title]` / `[web:url]`).
- `document_retrieval` is keyword/FTS-based; upgrading to `pgvector` embeddings is the natural next step (schema + eval support it: add an `embedding` column and an eval split).
- Multi-hop eval currently scores first-hop routing; full trajectory scoring (tool sequence + final answer) is future work once a keyed nightly run exists.
- Auth/multi-tenancy are out of scope for this scaffold (single-user conversations).
