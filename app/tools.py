"""The tool registry.

Every tool returns the same envelope so the UI and the audit trail can render any
call uniformly:

    {"tool": ..., "args": {...}, "data": ..., "sources": [...], "elapsed_ms": ...}

Two rules that matter more than the code:

* `spc_metrics` performs the arithmetic in Python. Capability is never asked of a
  language model — a plausible-looking number is worse than no number.
* `open_case` defaults to dry_run=True. Write actions are opt-in.
"""
from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any, Callable

from . import db
from .retrieval import get_kb
from .rules import MEASUREMENT_CODES, cpk, decide


class ToolValidationError(Exception):
    """Raised when a model asks for a tool with arguments we will not execute."""


# --- schema for argument validation ---------------------------------------
SCHEMAS: dict[str, dict[str, type]] = {
    "search_docs": {"query": str, "k": int},
    "query_orders": {"work_order_id": str},
    "defect_history": {"part_number": str, "limit": int},
    "spc_metrics": {"work_order_id": str, "feature": str},
    "warranty_rules": {"part_number": str, "defect_code": str, "work_order_id": str},
    "open_case": {"summary": str, "decision": str, "evidence": list, "dry_run": bool},
}

REQUIRED: dict[str, set[str]] = {
    "search_docs": {"query"},
    "query_orders": {"work_order_id"},
    "defect_history": {"part_number"},
    "spc_metrics": {"work_order_id"},
    "warranty_rules": {"part_number", "defect_code"},
    "open_case": {"summary", "decision", "evidence"},
}


def validate(tool: str, args: dict[str, Any], allowed: set[str] | None = None) -> dict[str, Any]:
    """Reject unknown tools, unknown keys and badly typed values before execution."""
    if tool not in SCHEMAS:
        raise ToolValidationError(f"unknown tool '{tool}'")
    if allowed is not None and tool not in allowed:
        raise ToolValidationError(f"tool '{tool}' is not permitted in this stage")
    schema = SCHEMAS[tool]
    unknown = set(args) - set(schema)
    if unknown:
        raise ToolValidationError(f"unknown argument(s) for {tool}: {sorted(unknown)}")
    missing = REQUIRED[tool] - set(args)
    if missing:
        raise ToolValidationError(f"missing required argument(s) for {tool}: {sorted(missing)}")
    for key, value in args.items():
        expected = schema[key]
        if expected is bool:
            if not isinstance(value, bool):
                raise ToolValidationError(f"{tool}.{key} must be a boolean")
        elif expected is int:
            if not isinstance(value, int) or isinstance(value, bool):
                raise ToolValidationError(f"{tool}.{key} must be an integer")
        elif not isinstance(value, expected):
            raise ToolValidationError(f"{tool}.{key} must be {expected.__name__}")
    return args


def _meta_as_of() -> date:
    """The dataset's reference date, so capability ages do not drift over time."""
    try:
        row = db.query_one("SELECT value FROM meta WHERE key = 'as_of'")
        if row:
            return datetime.fromisoformat(row["value"]).date()
    except Exception:
        pass
    return date.today()


# --- individual tools ------------------------------------------------------
def search_docs(query: str, k: int = 4) -> dict[str, Any]:
    started = time.perf_counter()
    hits = get_kb().search(query, k=k)
    return {
        "data": {"query": query, "hits": hits},
        "sources": [hit["chunk_id"] for hit in hits],
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


def query_orders(work_order_id: str) -> dict[str, Any]:
    started = time.perf_counter()
    row = db.query_one(
        """
        SELECT wo.id, wo.part_number, wo.line, wo.started_at, wo.quantity, wo.shift,
               p.name AS part_name, p.warranty_months, p.supplier_id,
               s.name AS supplier_name, s.country AS supplier_country, s.rating AS supplier_rating
        FROM work_orders wo
        JOIN parts p ON p.part_number = wo.part_number
        JOIN suppliers s ON s.id = p.supplier_id
        WHERE wo.id = ?
        """,
        (work_order_id,),
    )
    if row:
        age_days = (_meta_as_of() - datetime.fromisoformat(row["started_at"]).date()).days
        row["age_days"] = age_days
        row["warranty_days"] = row["warranty_months"] * 30
    return {
        "data": row or {"error": f"work order {work_order_id} not found"},
        "sources": [f"work_orders:{work_order_id}"] if row else [],
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


def defect_history(part_number: str, limit: int = 10) -> dict[str, Any]:
    started = time.perf_counter()
    by_code = db.query(
        """
        SELECT dr.defect_code, COUNT(*) AS n
        FROM defect_reports dr
        JOIN work_orders wo ON wo.id = dr.work_order_id
        WHERE wo.part_number = ?
        GROUP BY dr.defect_code
        ORDER BY n DESC
        """,
        (part_number,),
    )
    recent = db.query(
        """
        SELECT dr.id, dr.work_order_id, dr.defect_code, dr.severity, dr.reported_at
        FROM defect_reports dr
        JOIN work_orders wo ON wo.id = dr.work_order_id
        WHERE wo.part_number = ?
        ORDER BY dr.reported_at DESC
        LIMIT ?
        """,
        (part_number, limit),
    )
    total = sum(row["n"] for row in by_code)
    return {
        "data": {"part_number": part_number, "total_reports": total, "by_code": by_code, "recent": recent},
        "sources": [f"defect_reports:{part_number}"] if total else [],
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


def spc_metrics(work_order_id: str, feature: str | None = None) -> dict[str, Any]:
    """Compute capability in code. This is the guardrail the demo exists to show."""
    started = time.perf_counter()
    rows = db.query(
        "SELECT feature, measured_value, usl, lsl, target FROM spc_measurements WHERE work_order_id = ?",
        (work_order_id,),
    )
    if feature:
        rows = [row for row in rows if row["feature"] == feature]
    if not rows:
        return {
            "data": {
                "work_order_id": work_order_id,
                "available": False,
                "note": "no SPC measurements recorded for this work order",
            },
            "sources": [],
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }

    values = [row["measured_value"] for row in rows]
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1) if n > 1 else 0.0
    std = variance ** 0.5
    usl, lsl = rows[0]["usl"], rows[0]["lsl"]
    value = cpk(mean, std, usl, lsl)
    return {
        "data": {
            "work_order_id": work_order_id,
            "available": True,
            "feature": rows[0]["feature"],
            "n": n,
            "mean": round(mean, 4),
            "std": round(std, 4),
            "usl": usl,
            "lsl": lsl,
            "cpk": value,
            "computed_by": "python (not the model)",
        },
        "sources": [f"spc_measurements:{work_order_id}"],
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


def warranty_rules(part_number: str, defect_code: str, work_order_id: str | None = None) -> dict[str, Any]:
    """Apply the deterministic rule table and return a decision with its rule id.

    `work_order_id` matters: coverage must be evaluated against the work order the
    claim refers to, not against the most recent production run for that part. An
    earlier version did the latter and the evaluation set caught it (see README).
    """
    started = time.perf_counter()
    if work_order_id:
        order = db.query_one(
            """
            SELECT wo.id, wo.started_at, p.warranty_months, p.supplier_id
            FROM work_orders wo JOIN parts p ON p.part_number = wo.part_number
            WHERE wo.id = ? AND wo.part_number = ?
            """,
            (work_order_id, part_number),
        )
    else:
        order = None
    if not order:
        order = db.query_one(
            """
            SELECT wo.id, wo.started_at, p.warranty_months, p.supplier_id
            FROM work_orders wo JOIN parts p ON p.part_number = wo.part_number
            WHERE wo.part_number = ?
            ORDER BY wo.started_at DESC LIMIT 1
            """,
            (part_number,),
        )
    if not order:
        return {
            "data": {"error": f"no production record for {part_number}"},
            "sources": [],
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }

    age_days = (_meta_as_of() - datetime.fromisoformat(order["started_at"]).date()).days
    cpk_value = None
    if defect_code in MEASUREMENT_CODES:
        metrics = spc_metrics(order["id"])["data"]
        cpk_value = metrics.get("cpk") if metrics.get("available") else None

    supplier_rate = None
    row = db.query_one(
        """
        SELECT COUNT(dr.id) AS defects, SUM(wo.quantity) AS units
        FROM work_orders wo
        JOIN parts p ON p.part_number = wo.part_number
        LEFT JOIN defect_reports dr ON dr.work_order_id = wo.id
        WHERE p.supplier_id = ?
        """,
        (order["supplier_id"],),
    )
    if row and row["units"]:
        supplier_rate = round(row["defects"] / row["units"] * 1000, 2)

    result = decide(
        part_number=part_number,
        defect_code=defect_code,
        warranty_months=order["warranty_months"],
        age_days=age_days,
        cpk_value=cpk_value,
        supplier_defect_rate=supplier_rate,
    )
    payload = result.as_dict()
    payload.update(
        {
            "part_number": part_number,
            "defect_code": defect_code,
            "age_days": age_days,
            "warranty_months": order["warranty_months"],
            "cpk": cpk_value,
            "supplier_defect_rate_per_1k": supplier_rate,
        }
    )
    return {
        "data": payload,
        "sources": [f"warranty_policies:{result.rule_id}"],
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


def open_case(summary: str, decision: str, evidence: list, dry_run: bool = True) -> dict[str, Any]:
    started = time.perf_counter()
    payload = {
        "summary": summary,
        "decision": decision,
        "evidence": evidence,
        "dry_run": dry_run,
        "would_write_to": "cases table (not implemented in the demo)",
    }
    return {
        "data": payload,
        "sources": [],
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


REGISTRY: dict[str, Callable[..., dict[str, Any]]] = {
    "search_docs": search_docs,
    "query_orders": query_orders,
    "defect_history": defect_history,
    "spc_metrics": spc_metrics,
    "warranty_rules": warranty_rules,
    "open_case": open_case,
}


def call(tool: str, args: dict[str, Any], allowed: set[str] | None = None) -> dict[str, Any]:
    validate(tool, args, allowed=allowed)
    started = time.perf_counter()
    result = REGISTRY[tool](**args)
    return {
        "tool": tool,
        "args": args,
        "data": result["data"],
        "sources": result["sources"],
        "elapsed_ms": result.get("elapsed_ms", int((time.perf_counter() - started) * 1000)),
    }
