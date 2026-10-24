"""The staged agent.

Three stages, each gated by a checkpoint that can fail. This is deliberately the
opposite of a free-form ReAct loop: the model proposes, the code validates, and a
stage that cannot meet its evidence bar escalates instead of guessing.

    intake  -> checkpoint: classification enum + identifiable work order
    evidence-> checkpoint: >= 2 distinct sources, plus capability data when the
               defect code is measurement-dependent
    decision-> checkpoint: citation post-check (every cited id must exist)

Every step is written to an audit trail, including the failures.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import tools as tools_mod
from .config import LOG_DIR, SETTINGS
from .llm import BaseProvider, get_provider
from .rules import ALLOWED_DECISIONS, ESCALATE, MEASUREMENT_CODES

ALLOWED_TOOLS = {
    "intake": set(),
    "evidence": {"search_docs", "query_orders", "defect_history", "spc_metrics", "warranty_rules"},
    "decision": {"open_case"},
}
CITATION_RE = re.compile(r"\[([A-Za-z0-9_\-]+(?:#[^\]]+)?|(?:work_orders|defect_reports|spc_measurements|warranty_policies):[A-Za-z0-9_\-]+)\]")


# --------------------------------------------------------------------------
# audit trail
# --------------------------------------------------------------------------
class Audit:
    def __init__(self, case_id: str) -> None:
        self.case_id = case_id
        self.started = time.perf_counter()
        self.events: list[dict[str, Any]] = []

    def log(self, kind: str, stage: str, **detail: Any) -> dict[str, Any]:
        event = {
            "t_ms": int((time.perf_counter() - self.started) * 1000),
            "type": kind,
            "stage": stage,
            "detail": detail,
        }
        self.events.append(event)
        return event

    def dump(self) -> str:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / f"audit_{self.case_id}.json"
        path.write_text(json.dumps(self.events, indent=2, default=str), encoding="utf-8")
        return str(path)


# --------------------------------------------------------------------------
# result object
# --------------------------------------------------------------------------
@dataclass
class CaseResult:
    case_id: str
    question: str
    provider: str = "mock"
    stages: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    decision: dict[str, Any] = field(default_factory=dict)
    justification: str = ""
    confidence: float = 0.0
    escalated: bool = False
    escalation_reason: str = ""
    checkpoint_failures: int = 0
    guardrail_blocks: int = 0
    audit_path: str = ""
    audit: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    elapsed_ms: int = 0
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "question": self.question,
            "provider": self.provider,
            "stages": self.stages,
            "tool_calls": self.tool_calls,
            "evidence": self.evidence,
            "decision": self.decision,
            "justification": self.justification,
            "confidence": self.confidence,
            "escalated": self.escalated,
            "escalation_reason": self.escalation_reason,
            "checkpoint_failures": self.checkpoint_failures,
            "guardrail_blocks": self.guardrail_blocks,
            "usage": self.usage,
            "elapsed_ms": self.elapsed_ms,
            "audit_path": self.audit_path,
            "audit": self.audit,
            "error": self.error,
        }


# --------------------------------------------------------------------------
# the pipeline
# --------------------------------------------------------------------------
def run_case(
    question: str,
    *,
    case_id: str = "CASE-LIVE",
    provider: BaseProvider | None = None,
    max_tool_calls: int | None = None,
    confidence_threshold: float | None = None,
    unsafe_llm_math: bool = False,
    unsafe_skip_checkpoint: bool = False,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> CaseResult:
    """Run one claim end to end.

    The `unsafe_*` flags exist only for the Guardrails tab: they deliberately break
    a rule so the validator can be seen blocking it. Never set them in a real run.
    """
    llm = provider or get_provider()
    max_calls = max_tool_calls or SETTINGS.max_tool_calls
    threshold = SETTINGS.confidence_threshold if confidence_threshold is None else confidence_threshold

    result = CaseResult(case_id=case_id, question=question, provider=llm.name)
    audit = Audit(case_id)
    result.audit = audit.events
    started = time.perf_counter()

    def emit(event: dict[str, Any]) -> None:
        if on_event:
            on_event(event)

    def stage(name: str) -> dict[str, Any]:
        entry = {"stage": name, "status": "running", "notes": [], "started_ms": int((time.perf_counter() - started) * 1000)}
        result.stages.append(entry)
        event = audit.log("stage_start", name)
        emit(event)
        return entry

    def finish_stage(entry: dict[str, Any], status: str, note: str = "") -> None:
        entry["status"] = status
        if note:
            entry["notes"].append(note)
        entry["elapsed_ms"] = int((time.perf_counter() - started) * 1000) - entry["started_ms"]
        event = audit.log("stage_end", entry["stage"], status=status, note=note)
        emit(event)

    # ---------------------------------------------------------------- intake
    entry = stage("intake")
    intake = {}
    for attempt in (1, 2):
        try:
            intake = llm.classify_case(question)
        except Exception as exc:
            audit.log("llm_error", "intake", error=str(exc))
            intake = {}
        categories = {"product_defect", "supplier_issue", "policy_question"}
        ok = intake.get("category") in categories
        audit.log(
            "checkpoint", "intake", name="classification_enum",
            passed=bool(ok), attempt=attempt, value=intake.get("category"),
        )
        if ok:
            break
        result.checkpoint_failures += 1
        intake = {}

    work_order_id = (intake or {}).get("work_order_id")
    defect_code = (intake or {}).get("defect_code")

    order = None
    if work_order_id:
        call = tools_mod.call("query_orders", {"work_order_id": work_order_id}, allowed={"query_orders"})
        result.tool_calls.append(call)
        result.evidence.append({"id": f"work_orders:{work_order_id}", "type": "record", "summary": f"work order {work_order_id}"})
        audit.log("tool_call", "intake", tool="query_orders", args=call["args"], elapsed_ms=call["elapsed_ms"])
        order = call["data"]
        if order.get("error"):
            order = None
        else:
            defect_code = defect_code or None
    else:
        audit.log("checkpoint", "intake", name="work_order_identified", passed=False)

    if not order:
        finish_stage(entry, "failed", "no identifiable work order in the claim")
        result.escalated = True
        result.escalation_reason = "The claim text does not identify a work order, so no evidence can be retrieved."
        result.decision = {
            "decision": ESCALATE,
            "rule_id": "R-NO-ORDER",
            "certainty": 0.2,
            "reasons": [result.escalation_reason],
        }
        result.confidence = 0.2
        audit.log("escalation", "intake", reason=result.escalation_reason)
        result.audit_path = audit.dump()
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        result.usage = {"prompt_tokens": llm.usage.prompt_tokens, "completion_tokens": llm.usage.completion_tokens}
        return result

    part_number = order["part_number"]
    if not defect_code:
        # No silent default here: an unidentified defect mode is exactly the kind of
        # gap that must surface as an escalation rather than become a confident guess.
        audit.log("checkpoint", "intake", name="defect_code_identified", passed=False)
        result.checkpoint_failures += 1
        finish_stage(entry, "failed", "defect mode could not be identified from the claim")
        result.escalated = True
        result.escalation_reason = (
            "The claim does not state an identifiable defect mode, so no disposition rule can be applied."
        )
        result.decision = {
            "decision": ESCALATE,
            "rule_id": "R-NO-CODE",
            "certainty": 0.2,
            "reasons": [result.escalation_reason],
        }
        result.confidence = 0.2
        audit.log("escalation", "intake", reason=result.escalation_reason)
        result.audit_path = audit.dump()
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        result.usage = {"prompt_tokens": llm.usage.prompt_tokens, "completion_tokens": llm.usage.completion_tokens}
        return result

    entry["notes"].append(f"{intake.get('category', 'unknown')} · {part_number} · {defect_code}")
    finish_stage(entry, "passed")

    # -------------------------------------------------------------- evidence
    entry = stage("evidence")
    called: list[dict[str, Any]] = []
    rounds = 2  # one normal pass, one retry if the checkpoint fails
    checkpoint_passed = False

    for round_no in range(1, rounds + 1):
        allowed = ALLOWED_TOOLS["evidence"]
        remaining = max_calls - len(called)
        for _ in range(max(0, remaining)):
            state = {
                "question": question,
                "work_order_id": work_order_id,
                "part_number": part_number,
                "defect_code": defect_code,
                "called": [{"tool": c["tool"], "args": c["args"]} for c in called],
                "round": round_no,
            }
            try:
                proposal = llm.choose_tool(state)
            except Exception as exc:
                audit.log("llm_error", "evidence", error=str(exc))
                break

            tool_name = proposal.get("tool")
            args = proposal.get("args") or {}
            if tool_name == "finish":
                audit.log("agent_finish", "evidence", round=round_no, reason=args.get("reason", ""))
                break

            try:
                tools_mod.validate(tool_name, args, allowed=allowed)
            except tools_mod.ToolValidationError as exc:
                result.guardrail_blocks += 1
                event = audit.log(
                    "guardrail_block", "evidence", tool=tool_name, args=args, reason=str(exc),
                )
                emit(event)
                continue

            # Guardrail demo: let the "model" produce the capability number.
            if unsafe_llm_math and tool_name == "spc_metrics":
                guess = _model_cpk_guess(llm, work_order_id, part_number)
                real = tools_mod.call("spc_metrics", args, allowed=allowed)["data"]
                # Any disagreement beyond rounding is enough: the number is not the
                # model's to produce, so the computed value always wins.
                blocked = real.get("available") and (
                    guess is None or abs(float(guess) - float(real.get("cpk") or 0)) > 0.05
                )
                if blocked:
                    result.guardrail_blocks += 1
                    event = audit.log(
                        "guardrail_block",
                        "evidence",
                        name="capability_must_be_computed",
                        model_value=guess,
                        code_value=real.get("cpk"),
                        reason="model-estimated Cpk disagreed with the computed value; using the computed one",
                    )
                    emit(event)
                call = {
                    "tool": "spc_metrics",
                    "args": args,
                    "data": real,
                    "sources": [f"spc_measurements:{work_order_id}"] if real.get("available") else [],
                    "elapsed_ms": 0,
                }
                called.append(call)
                result.tool_calls.append(call)
                continue

            call = tools_mod.call(tool_name, args, allowed=allowed)
            called.append(call)
            result.tool_calls.append(call)
            audit.log("tool_call", "evidence", tool=tool_name, args=args, elapsed_ms=call["elapsed_ms"],
                      sources=call["sources"][:4])

            for source in call["sources"]:
                if not any(ev["id"] == source for ev in result.evidence):
                    result.evidence.append(
                        {"id": source, "type": "document" if _looks_like_doc(source) else "record",
                         "summary": _summarise(call, source)}
                    )

        # -- evidence checkpoint
        doc_sources = [ev for ev in result.evidence if ev["type"] == "document"]
        data_sources = [ev for ev in result.evidence if ev["type"] == "record"]
        has_spc = any(
            call["tool"] == "spc_metrics" and (call["data"] or {}).get("available")
            for call in called
        )
        needs_spc = defect_code in MEASUREMENT_CODES

        problems = []
        if len(doc_sources) < 1:
            problems.append("no document evidence retrieved")
        if len(data_sources) < 1:
            problems.append("no production record retrieved")
        if needs_spc and not has_spc:
            problems.append(f"{defect_code} requires a capability record and none is available")

        if unsafe_skip_checkpoint:
            if problems:
                event = audit.log(
                    "unsafe_override", "evidence",
                    skipped=problems,
                    reason="checkpoint bypassed by the Guardrails toggle",
                )
                emit(event)
            problems = []

        passed = not problems
        event = audit.log(
            "checkpoint", "evidence", name="evidence_sufficiency", passed=passed,
            round=round_no, problems=problems,
            doc_sources=len(doc_sources), data_sources=len(data_sources), spc=has_spc,
        )
        emit(event)

        if passed:
            checkpoint_passed = True
            break
        result.checkpoint_failures += 1
        if round_no < rounds:
            audit.log("retry", "evidence", round=round_no + 1, reason=problems)
        else:
            result.escalated = True
            result.escalation_reason = (
                "Evidence checkpoint failed after one retry: " + "; ".join(problems)
            )

    if checkpoint_passed:
        entry["notes"].append(f"{len(result.tool_calls)} tool calls · {len(result.evidence)} sources")
        finish_stage(entry, "passed")
    else:
        finish_stage(entry, "failed", result.escalation_reason or "evidence insufficient")

    # -------------------------------------------------------------- decision
    entry = stage("decision")
    rule_data = None
    for call in result.tool_calls:
        if call["tool"] == "warranty_rules" and "decision" in (call["data"] or {}):
            rule_data = call["data"]
    if rule_data is None:
        # The rules must run even if the model never asked for them: the decision is
        # not the model's to make.
        call = tools_mod.call(
            "warranty_rules",
            {"part_number": part_number, "defect_code": defect_code, "work_order_id": work_order_id},
            allowed={"warranty_rules"},
        )
        result.tool_calls.append(call)
        audit.log("tool_call", "decision", tool="warranty_rules", args=call["args"],
                  injected=True, reason="rule engine run was mandatory")
        rule_data = call["data"]
        if call["sources"]:
            for source in call["sources"]:
                if not any(ev["id"] == source for ev in result.evidence):
                    result.evidence.append(
                        {"id": source, "type": "record", "summary": "applied policy rule"}
                    )

    decision = {
        "decision": rule_data.get("decision", ESCALATE),
        "rule_id": rule_data.get("rule_id", "R-UNKNOWN"),
        "certainty": float(rule_data.get("certainty", 0.3)),
        "reasons": rule_data.get("reasons", []),
        "facts": {
            "part_number": part_number,
            "defect_code": defect_code,
            "age_days": rule_data.get("age_days"),
            "warranty_months": rule_data.get("warranty_months"),
            "cpk": rule_data.get("cpk"),
        },
    }
    if decision["decision"] not in ALLOWED_DECISIONS:
        result.checkpoint_failures += 1
        audit.log("checkpoint", "decision", name="decision_enum", passed=False, value=decision["decision"])
        decision["decision"] = ESCALATE

    # confidence = rule certainty × evidence coverage
    required = 2 + (1 if defect_code in MEASUREMENT_CODES else 0)
    doc_sources = [ev for ev in result.evidence if ev["type"] == "document"]
    data_sources = [ev for ev in result.evidence if ev["type"] == "record"]
    has_spc = any(
        call["tool"] == "spc_metrics" and (call["data"] or {}).get("available")
        for call in result.tool_calls
    )
    satisfied = (1 if doc_sources else 0) + (1 if data_sources else 0)
    if defect_code in MEASUREMENT_CODES:
        satisfied += 1 if has_spc else 0
    coverage = satisfied / required
    confidence = round(min(0.99, decision["certainty"] * (0.55 + 0.45 * coverage)), 2)

    if not result.escalated and confidence < threshold:
        result.escalated = True
        result.escalation_reason = (
            f"Confidence {confidence} is below the {threshold} threshold: "
            f"rule {decision['rule_id']} with evidence coverage {coverage:.0%}."
        )
        audit.log("escalation", "decision", reason=result.escalation_reason, confidence=confidence)

    # the justification is written by the model, but only about a settled decision
    try:
        justification = llm.write_justification(decision, result.evidence)
    except Exception as exc:
        audit.log("llm_error", "decision", error=str(exc))
        justification = " ".join(decision["reasons"])

    justification, citation_ok = _enforce_citations(
        justification, result.evidence, decision, llm, audit
    )
    if not citation_ok and not unsafe_skip_checkpoint:
        result.checkpoint_failures += 1
        audit.log(
            "checkpoint", "decision", name="citation_post_check", passed=False,
            note="justification was regenerated from the evidence set",
        )

    result.decision = decision
    result.justification = justification
    result.confidence = confidence
    entry["notes"].append(f"{decision['decision']} · rule {decision['rule_id']} · confidence {confidence}")
    finish_stage(entry, "passed")

    if result.escalated and decision["decision"] != ESCALATE:
        # The rule result stands, but the case still goes to a human.
        audit.log("human_review", "decision", rule_decision=decision["decision"],
                  reason=result.escalation_reason)
    elif result.escalated:
        audit.log("human_review", "decision", rule_decision=ESCALATE,
                  reason=result.escalation_reason or "policy requires human disposition")

    result.audit_path = audit.dump()
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    result.usage = {
        "prompt_tokens": llm.usage.prompt_tokens,
        "completion_tokens": llm.usage.completion_tokens,
        "total_tokens": llm.usage.total,
    }
    return result


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _looks_like_doc(source: str) -> bool:
    return "#" in source and not source.startswith(("work_orders", "defect_reports", "spc_measurements", "warranty_policies"))


def _summarise(call: dict[str, Any], source: str) -> str:
    if call["tool"] == "search_docs":
        for hit in call["data"].get("hits", []):
            if hit["chunk_id"] == source:
                return hit["text"][:140]
    if call["tool"] == "spc_metrics":
        return "capability record (mean, std, Cpk)"
    if call["tool"] == "warranty_rules":
        return f"applied rule {call['data'].get('rule_id')}"
    if call["tool"] == "defect_history":
        return "defect history for the part"
    return "record"


def _model_cpk_guess(llm: BaseProvider, work_order_id: str, part_number: str) -> float | None:
    """A deliberately naive 'model estimate', used only to demonstrate the guardrail.

    An optimistic round number is exactly what a model produces when asked to
    estimate capability without computing it.
    """
    return 1.45


def _enforce_citations(
    text: str,
    evidence: list[dict[str, Any]],
    decision: dict[str, Any],
    llm: BaseProvider,
    audit: Audit,
) -> tuple[str, bool]:
    """Every [id] in the justification must exist in the evidence set.

    Unsupported citations are treated as a defect in the output, not as a style
    problem: the text is regenerated once, then rebuilt from the evidence ids.
    """
    valid_ids = {ev["id"] for ev in evidence}
    cited = CITATION_RE.findall(text)
    unknown = [c for c in cited if c not in valid_ids]

    if not cited:
        audit.log("checkpoint", "decision", name="citation_present", passed=False,
                  note="no citations in justification")
        return _rebuild_text(decision, evidence), False

    if unknown:
        audit.log("citation_reject", "decision", unknown=unknown,
                  note="model cited ids that are not in the evidence set; regenerating once")
        corrected = dict(decision)
        corrected["reasons"] = list(decision.get("reasons", [])) + [
            f"Only these evidence ids may be cited: {sorted(valid_ids)}."
        ]
        try:
            retry = llm.write_justification(corrected, evidence)
            retry_cited = CITATION_RE.findall(retry)
            if retry_cited and all(c in valid_ids for c in retry_cited):
                audit.log("checkpoint", "decision", name="citation_post_check", passed=True,
                          note="regenerated justification passed")
                return retry, True
        except Exception as exc:  # pragma: no cover
            audit.log("llm_error", "decision", error=str(exc))
        return _rebuild_text(decision, evidence), False

    audit.log("checkpoint", "decision", name="citation_post_check", passed=True,
              cited=len(cited))
    return text, True


def _rebuild_text(decision: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
    ids = ", ".join(f"[{ev['id']}]" for ev in evidence[:6]) or "[no evidence]"
    reason = " ".join(decision.get("reasons", [])[:2])
    return (
        f"Decision: {decision['decision'].replace('_', ' ')} (rule {decision['rule_id']}). "
        f"{reason} Evidence: {ids}."
    )


# --------------------------------------------------------------------------
# evaluation
# --------------------------------------------------------------------------
def run_eval(cases: list[dict[str, Any]], provider: BaseProvider | None = None) -> dict[str, Any]:
    """Run every case and report what actually happened."""
    from .config import SETTINGS as _S

    llm = provider or get_provider()
    rows = []
    matched = 0
    total_calls = 0
    escalations = 0
    checkpoint_failures = 0
    guardrail_blocks = 0
    tokens = 0
    latency = 0

    for case in cases:
        result = run_case(
            case["question"],
            case_id=case["case_id"],
            provider=llm,
            confidence_threshold=_S.confidence_threshold,
        )
        outcome = result.decision.get("decision")
        ok = outcome == case["expected_outcome"]
        matched += 1 if ok else 0
        total_calls += len(result.tool_calls)
        escalations += 1 if result.escalated else 0
        checkpoint_failures += result.checkpoint_failures
        guardrail_blocks += result.guardrail_blocks
        tokens += result.usage.get("total_tokens", 0)
        latency += result.elapsed_ms
        rows.append(
            {
                "case_id": case["case_id"],
                "expected": case["expected_outcome"],
                "actual": outcome,
                "match": ok,
                "rule": result.decision.get("rule_id"),
                "confidence": result.confidence,
                "escalated": result.escalated,
                "tool_calls": len(result.tool_calls),
                "checkpoint_failures": result.checkpoint_failures,
                "elapsed_ms": result.elapsed_ms,
                "defect_code": case.get("defect_code"),
            }
        )

    n = max(1, len(cases))
    # gpt-4o-mini pricing, only meaningful when a real provider is used
    cost = (tokens / 1_000_000) * 0.30
    return {
        "rows": rows,
        "metrics": {
            "cases": len(cases),
            "decision_match_pct": round(matched / n * 100, 1),
            "escalation_rate_pct": round(escalations / n * 100, 1),
            "avg_tool_calls": round(total_calls / n, 2),
            "checkpoint_failures": checkpoint_failures,
            "guardrail_blocks": guardrail_blocks,
            "avg_latency_ms": round(latency / n),
            "total_tokens": tokens,
            "estimated_cost_usd": round(cost, 5),
            "provider": llm.name,
        },
    }
