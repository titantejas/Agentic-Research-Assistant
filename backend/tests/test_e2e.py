"""End-to-end tests (stdlib + fastapi only — no DB, no LLM key).

What runs here:
  EVAL-DATA  dataset integrity (100 rows, category counts, required fields)
  CALC       all 25 calculator expectations through live app.guards.calc_eval
  SQL        all 25 guardrail expectations through live app.guards.is_select_allowed
  ROUTER     full 100-query routing accuracy through live app.router (>= 90%)
  CACHE      cache-key determinism / normalization / conversation scoping
  SSE        SSE framing round-trip (mirrors frontend/src/api.ts parser)
  API        real FastAPI app (app.main) over TestClient with stubbed
             langchain/sse_starlette/DB: /health + POST /chat/stream event order

Run:  python -m unittest backend.tests.test_e2e -v      (from repo root)
   or python backend/tests/test_e2e.py
"""
import json
import sys
import unittest
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

from app.guards import is_select_allowed, calc_eval, cache_key_fn  # noqa: E402
from app.router import predict_tool  # noqa: E402

DATA = BACKEND / "evals" / "eval_data.jsonl"


def load_rows():
    return [json.loads(l) for l in DATA.read_text().splitlines() if l.strip()]


def parse_sse(raw: str):
    """Python mirror of frontend/src/api.ts streamChat framing."""
    events = []
    for frame in raw.split("\n\n"):
        line = next((l for l in frame.splitlines() if l.startswith("data:")), None)
        if not line:
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        events.append(json.loads(payload))
    return events


# ---------------------------------------------------------------- stubs
def install_stubs():
    """Stub third-party modules that are unavailable offline so the REAL
    app.main can be imported (DB + LLM stay mocked at the boundary)."""
    if "app.main" in sys.modules:
        return

    ps = ModuleType("pydantic_settings")

    class BaseSettings:  # minimal stand-in: class attrs are the defaults
        def __init__(self, **kw):
            for klass in type(self).__mro__:
                for k, v in vars(klass).items():
                    if k.startswith("_") or k == "Config" or callable(v):
                        continue
                    if not hasattr(self, k):
                        setattr(self, k, v)
            for k, v in kw.items():
                setattr(self, k, v)

    ps.BaseSettings = BaseSettings
    sys.modules["pydantic_settings"] = ps

    lc = ModuleType("langchain_core")
    lc_tools = ModuleType("langchain_core.tools")
    lc_tools.tool = lambda fn=None, **kw: (fn if callable(fn) else (lambda f: f))
    lc_prompts = ModuleType("langchain_core.prompts")

    class ChatPromptTemplate:
        @classmethod
        def from_messages(cls, msgs):
            return cls()

    class MessagesPlaceholder:
        def __init__(self, *a, **k):
            pass

    lc_prompts.ChatPromptTemplate = ChatPromptTemplate
    lc_prompts.MessagesPlaceholder = MessagesPlaceholder
    lc_openai = ModuleType("langchain_openai")

    class ChatOpenAI:
        def __init__(self, *a, **k):
            pass

    lc_openai.ChatOpenAI = ChatOpenAI
    lc_pkg = ModuleType("langchain")
    lc_agents = ModuleType("langchain.agents")
    lc_agents.create_tool_calling_agent = lambda *a, **k: object()

    class AgentExecutor:
        def __init__(self, *a, **k):
            pass

        async def astream_events(self, *a, **k):
            if False:
                yield None

    lc_agents.AgentExecutor = AgentExecutor
    for name, mod in [("langchain_core", lc), ("langchain_core.tools", lc_tools),
                      ("langchain_core.prompts", lc_prompts),
                      ("langchain_openai", lc_openai), ("langchain", lc_pkg),
                      ("langchain.agents", lc_agents)]:
        sys.modules[name] = mod

    # Fake DB boundary: no real Postgres in unit tests.
    fake_db = ModuleType("app.db")

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    fake_db.SessionLocal = lambda: _Session()

    async def init_db():
        return None

    fake_db.init_db = init_db
    sys.modules["app.db"] = fake_db

    # sse_starlette stand-in backed by a real Starlette StreamingResponse
    # so TestClient exercises genuine SSE bytes end to end.
    from starlette.responses import StreamingResponse
    sse_pkg = ModuleType("sse_starlette")
    sse_sse = ModuleType("sse_starlette.sse")

    class EventSourceResponse(StreamingResponse):
        def __init__(self, content, **kw):
            async def gen():
                async for chunk in content:
                    if isinstance(chunk, dict) and "data" in chunk:
                        yield f"data: {chunk['data']}\n\n".encode()
                    else:
                        yield f"data: {chunk}\n\n".encode()

            super().__init__(gen(), media_type="text/event-stream", **kw)

    sse_sse.EventSourceResponse = EventSourceResponse
    sys.modules["sse_starlette"] = sse_pkg
    sys.modules["sse_starlette.sse"] = sse_sse


async def fake_run_stream(query, conv_id):
    cid = conv_id or "test-conv-id"

    def evt(t, d):
        return json.dumps({"type": t, "conversation_id": cid, "data": d})

    yield evt("reasoning", "planning")
    yield evt("tool_start", {"tool": "calculator", "input": query})
    yield evt("tool_end", {"tool": "calculator", "output": "42"})
    yield evt("token", "The answer is 42")
    yield evt("done", "The answer is 42")


class TestEvalData(unittest.TestCase):
    def test_100_rows_with_expected_shape(self):
        rows = load_rows()
        self.assertEqual(len(rows), 100)
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["category"]] = counts.get(r["category"], 0) + 1
            self.assertIn("query", r)
            self.assertTrue(r.get("expected_tool") or r.get("expected_first"))
        self.assertEqual(counts,
                         {"calculator": 25, "sql": 25, "docs": 25, "web": 15, "multi": 10})


class TestCalculator(unittest.TestCase):
    def test_all_25_expectations(self):
        for r in [r for r in load_rows() if r["category"] == "calculator"]:
            with self.subTest(r["id"]):
                self.assertEqual(calc_eval(r["expression"]), r["expected"])

    def test_rejects_injection(self):
        self.assertTrue(calc_eval("__import__('os').system('x')").startswith("Error:"))


class TestSqlGuardrail(unittest.TestCase):
    def test_all_25_expectations(self):
        for r in [r for r in load_rows() if r["category"] == "sql"]:
            with self.subTest(r["id"]):
                allowed, _ = is_select_allowed(r["sql"])
                self.assertEqual(allowed, r["expected_allowed"])


class TestRouter(unittest.TestCase):
    def test_full_routing_accuracy_ge_90(self):
        rows = load_rows()
        ok = sum(1 for r in rows
                 if predict_tool(r["query"]) == (r.get("expected_tool") or r.get("expected_first")))
        self.assertGreaterEqual(ok / len(rows), 0.90, f"routing {ok}/100")


class TestCacheKey(unittest.TestCase):
    def test_normalization_and_scoping(self):
        self.assertEqual(cache_key_fn("  Hello? ", "c1"), cache_key_fn("hello?", "c1"))
        self.assertNotEqual(cache_key_fn("hello?", "c1"), cache_key_fn("hello?", "c2"))
        self.assertEqual(len(cache_key_fn("x", None)), 32)


class TestSseFraming(unittest.TestCase):
    def test_round_trip_order(self):
        raw = "".join(
            f"data: {json.dumps(e)}\n\n" for e in [
                {"type": "reasoning", "data": "planning"},
                {"type": "tool_start", "data": {"tool": "calculator"}},
                {"type": "token", "data": "42"},
                {"type": "done", "data": "42"}])
        kinds = [e["type"] for e in parse_sse(raw)]
        self.assertEqual(kinds, ["reasoning", "tool_start", "token", "done"])


class TestApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install_stubs()
        import app.main as main_mod
        main_mod.run_stream = fake_run_stream  # mock LLM+DB boundary
        from fastapi.testclient import TestClient
        cls.client = TestClient(main_mod.app)

    def test_health(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True})

    def test_chat_stream_event_order(self):
        r = self.client.post("/chat/stream", json={"query": "Calculate 6*7"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/event-stream", r.headers["content-type"])
        kinds = [e["type"] for e in parse_sse(r.text)]
        self.assertEqual(kinds, ["reasoning", "tool_start", "tool_end", "token", "done"])
        done = parse_sse(r.text)[-1]
        self.assertEqual(done["data"], "The answer is 42")
        self.assertEqual(done["conversation_id"], "test-conv-id")


if __name__ == "__main__":
    unittest.main(verbosity=2)
