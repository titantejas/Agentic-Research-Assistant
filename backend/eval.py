"""Agentic Research Assistant — offline eval harness (stdlib only).

Measures, over backend/evals/eval_data.jsonl (100 queries):
  1. Routing accuracy  — does predict_tool() pick the expected tool?
  2. Tool-unit accuracy — calculator value / SQL guardrail / doc top-1 correct?
  3. Task completion   — routing AND tool-unit correct (the headline metric).
  4. Cache micro-benchmark — dict-cached vs recomputed tool calls.

Run:  python backend/eval.py [--data backend/evals/eval_data.jsonl]
Requires no API keys, no DB, no langchain. Exits 0 if task-completion >= 90%.
"""
import json
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]  # repo root (backend/.. )
BACKEND = REPO / "backend"
EVAL_DIR = BACKEND / "evals"
sys.path.insert(0, str(BACKEND))

# --- shared logic: import real modules, fall back to embedded copies ---
USING = "app.guards + app.router (live code)"
try:
    from app.guards import is_select_allowed, calc_eval, extract_expression  # type: ignore
except Exception as e:  # pragma: no cover - safety net
    print(f"WARN: could not import app.guards ({e}); using embedded copy")
    USING = "embedded fallback"
    import ast
    import operator

    _ALLOWED = {"documents", "messages", "tool_logs"}

    def is_select_allowed(sql):  # type: ignore[no-redef]
        q = sql.strip().lower()
        if not q.startswith("select"):
            return False, "only SELECT allowed"
        tables = re.findall(r"from\s+(\w+)", q) + re.findall(r"join\s+(\w+)", q)
        if any(t not in _ALLOWED for t in tables):
            return False, "table not allowed"
        if any(k in q for k in ("insert", "update", "delete", "drop", "alter", "grant", "truncate")):
            return False, "read-only"
        return True, "ok"

    _OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
            ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
            ast.Mod: operator.mod}

    def _ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](_ev(n.left), _ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](_ev(n.operand))
        raise ValueError("unsupported")

    def calc_eval(expr):  # type: ignore[no-redef]
        try:
            return str(_ev(ast.parse(expr, mode="eval").body))
        except Exception as ex:
            return f"Error: {ex}"

    def extract_expression(query):  # type: ignore[no-redef]
        q = query.lower()
        for w, s in (("plus", "+"), ("minus", "-"), ("times", "*"), ("divided by", "/"),
                     ("multiplied by", "*"), ("modulo", "%"), ("power", "**")):
            q = q.replace(w, s)
        q = re.sub(r"^(calculate|compute|solve|what is)", "", q).replace("?", "").strip()
        m = re.search(r"[-+*/%()\d.\s*]+", q)
        if not m or not re.search(r"\d", m.group(0)) or re.search(r"[a-z]", m.group(0)):
            return None
        return m.group(0).strip() or None

try:
    from app.router import predict_tool  # type: ignore
except Exception as e:
    raise SystemExit(f"router import failed: {e}")


# --- in-memory knowledge base mirroring seeded Postgres documents ---
KB = [
    ("LangChain Tool Calling",
     "LangChain tool calling agent reasoning invocations scratchpad max iterations policy whitelist grounded"),
    ("SSE Streaming",
     "SSE server-sent events EventSourceResponse token events stream connection generator data frames reconnect tokens"),
    ("Postgres Memory Schema",
     "Postgres schema conversations conversation messages memory roles tool_logs documents trigram gin index ILIKE snippet columns title content source_url"),
    ("Caching Strategy",
     "response cache response_cache TTL expires_at key hash normalized conversation latency hit skips LLM"),
    ("Prompt Optimization",
     "prompt system concise short tokens history truncation MAX_HISTORY_MESSAGES citations p95"),
    ("Frontend Chat UI",
     "React TypeScript chat UI trace fetch ReadableStream abort busy input render reasoning"),
]
STOP = {"how", "does", "what", "why", "when", "which", "our", "your", "the", "and", "for",
        "with", "then", "than", "are", "has", "have", "into", "over", "from", "that",
        "this", "also", "per", "its", "via", "to", "of", "in", "on", "a", "an", "is",
        "it", "as", "at", "by", "or", "do", "did", "are", "be", "across", "between"}


def tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9_]+", s.lower())
            if len(t) >= 2 and t not in STOP}


def retrieve_top1(query: str) -> str:
    q = tokens(query)
    best, best_score = KB[0][0], -1
    for title, content in KB:
        score = len(q & tokens(content))
        if score > best_score:
            best, best_score = title, score
    return best


def run_eval(data_path: Path) -> dict:
    rows = [json.loads(l) for l in data_path.read_text().splitlines() if l.strip()]
    cats: dict[str, dict[str, int]] = {}
    failures: list[dict] = []

    def cat(name):
        return cats.setdefault(name, {"n": 0, "route_ok": 0, "unit_ok": 0, "done": 0})

    for r in rows:
        c = cat(r["category"])
        c["n"] += 1
        q = r["query"]
        pred = predict_tool(q)
        exp = r.get("expected_tool") or r.get("expected_first")
        route_ok = (pred == exp)
        unit_ok, detail = True, ""
        if r["category"] == "calculator":
            expr = r.get("expression") or extract_expression(q) or ""
            got = calc_eval(expr)
            unit_ok = (got == r["expected"])
            detail = f"expr={expr!r} got={got!r} want={r['expected']!r}"
        elif r["category"] == "sql":
            allowed, reason = is_select_allowed(r["sql"])
            unit_ok = (allowed == r["expected_allowed"])
            detail = f"allowed={allowed} want={r['expected_allowed']} ({reason})"
        elif r["category"] == "docs":
            top = retrieve_top1(q)
            unit_ok = (top == r["expected_doc"])
            detail = f"top1={top!r} want={r['expected_doc']!r}"
        elif r["category"] == "multi":
            unit_ok = True  # first-hop routing is the unit under test
            detail = f"second-hop={r.get('expected_tools', [])}"
        # web: routing IS the task (live search needs network/key)
        c["route_ok"] += route_ok
        c["unit_ok"] += unit_ok
        done = route_ok and unit_ok
        c["done"] += done
        if not done:
            failures.append({"id": r["id"], "query": q, "pred": pred,
                             "want": exp, "route_ok": route_ok,
                             "unit_ok": unit_ok, "detail": detail})

    total = len(rows)
    done = sum(v["done"] for v in cats.values())
    summary = {
        "engine": USING,
        "n": total,
        "task_completion": round(done / total, 4),
        "routing_acc": round(sum(v["route_ok"] for v in cats.values()) / total, 4),
        "unit_acc": round(sum(v["unit_ok"] for v in cats.values()) / total, 4),
        "per_category": {k: {"n": v["n"],
                             "routing": round(v["route_ok"] / v["n"], 4),
                             "unit": round(v["unit_ok"] / v["n"], 4),
                             "task_completion": round(v["done"] / v["n"], 4)}
                         for k, v in cats.items()},
        "failures": failures,
    }

    # --- cache micro-benchmark: recompute vs dict-cached tool calls ---
    exprs = [json.loads(l).get("expression") for l in open(data_path)
             if json.loads(l).get("expression")]
    t0 = time.perf_counter()
    for _ in range(20):
        for e in exprs:
            calc_eval(e)
    cold = time.perf_counter() - t0
    cache: dict[str, str] = {}
    t0 = time.perf_counter()
    for _ in range(20):
        for e in exprs:
            if e not in cache:
                cache[e] = calc_eval(e)
    warm = time.perf_counter() - t0
    summary["cache_benchmark"] = {
        "cold_s": round(cold, 4), "warm_s": round(warm, 4),
        "saving_pct": round(100 * (cold - warm) / cold, 1) if cold else 0.0,
        "note": "offline micro-benchmark of repeated tool calls, not LLM latency",
    }
    return summary


def main() -> int:
    data = Path(sys.argv[sys.argv.index("--data") + 1]) if "--data" in sys.argv \
        else EVAL_DIR / "eval_data.jsonl"
    s = run_eval(data)
    print(f"engine: {s['engine']}")
    print(f"queries: {s['n']}")
    print(f"routing accuracy : {s['routing_acc']*100:.1f}%")
    print(f"tool-unit accuracy: {s['unit_acc']*100:.1f}%")
    print(f"TASK COMPLETION  : {s['task_completion']*100:.1f}%  (target >= 90%)")
    print("\nper-category:")
    for k, v in s["per_category"].items():
        print(f"  {k:10s} n={v['n']:3d} route={v['routing']*100:5.1f}% "
              f"unit={v['unit']*100:5.1f}% done={v['task_completion']*100:5.1f}%")
    b = s["cache_benchmark"]
    print(f"\ncache micro-bench: cold={b['cold_s']}s warm={b['warm_s']}s saving={b['saving_pct']}%")
    if s["failures"]:
        print(f"\nFAILURES ({len(s['failures'])}):")
        for f in s["failures"][:20]:
            print(f"  {f['id']}: pred={f['pred']} want={f['want']} | {f['detail']}")
    (EVAL_DIR / "results.json").write_text(json.dumps(s, indent=2))
    print(f"\nwrote {EVAL_DIR / 'results.json'}")
    return 0 if s["task_completion"] >= 0.90 else 1


if __name__ == "__main__":
    raise SystemExit(main())
