"""Pure-stdlib helpers shared by tools.py, evals and tests.

Kept dependency-free so `python backend/eval.py` and
`python -m unittest` run without langchain / postgres installed.
"""
import ast
import hashlib
import operator
import re

ALLOWED_TABLES = {"documents", "messages", "tool_logs"}
_WRITE_KEYWORDS = ("insert", "update", "delete", "drop", "alter", "grant", "truncate")


def is_select_allowed(sql: str) -> tuple[bool, str]:
    """Guardrail mirror of tools.sql_query. Returns (allowed, reason)."""
    q = sql.strip().lower()
    if not q.startswith("select"):
        return False, "only SELECT allowed"
    tables = re.findall(r"from\s+(\w+)", q) + re.findall(r"join\s+(\w+)", q)
    if any(t not in ALLOWED_TABLES for t in tables):
        return False, f"only {sorted(ALLOWED_TABLES)} allowed"
    if any(k in q for k in _WRITE_KEYWORDS):
        return False, "read-only"
    return True, "ok"


_ops = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.Mod: operator.mod,
}


def _eval_node(node: ast.AST):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ops:
        return _ops[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ops:
        return _ops[type(node.op)](_eval_node(node.operand))
    raise ValueError("unsupported expression")


def calc_eval(expression: str) -> str:
    """Safe arithmetic eval. Returns numeric string or 'Error: ...'."""
    try:
        return str(_eval_node(ast.parse(expression, mode="eval").body))
    except Exception as e:
        return f"Error: {e}"


def extract_expression(query: str) -> str | None:
    """Pull a bare arithmetic expression out of natural language."""
    q = query.lower().replace("what is", "").replace("calculate", "").replace("compute", "")
    q = q.replace("plus", "+").replace("minus", "-").replace("times", "*").replace("divided by", "/")
    q = q.replace("multiplied by", "*").replace("modulo", "%").replace("mod", "%").replace("power", "**")
    q = q.replace("?", "").strip()
    m = re.search(r"[-+*/%()\d.\s*]+", q)
    if not m:
        return None
    expr = m.group(0).strip()
    if not re.search(r"\d", expr):
        return None
    if re.search(r"[a-z]", expr):
        return None
    return expr or None


def cache_key_fn(query: str, conversation_id: str | None) -> str:
    return hashlib.sha256(f"{query.strip().lower()}|{conversation_id or 'none'}".encode()).hexdigest()[:32]
