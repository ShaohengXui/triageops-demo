"""Pipeline tests: the checkpoints have to fail in the ways they claim to."""
from __future__ import annotations

from app.agent import run_case
from app.llm import MockProvider


class LyingProvider(MockProvider):
    """A model that cites evidence it never retrieved. The post-check must catch it."""

    name = "mock"

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def write_justification(self, decision, evidence):
        self.calls += 1
        return "Approved because SOP-999#Imaginary section says so. [SOP-999#Imaginary section]"


def test_claim_without_work_order_escalates(cases):
    claim = "A customer says something is wrong with the part. Please advise."
    result = run_case(claim, case_id="TEST-NO-ORDER")
    assert result.escalated is True
    assert result.decision["rule_id"] == "R-NO-ORDER"


def test_claim_without_defect_mode_escalates():
    claim = "Customer complaint about NX-1042 from work order WO-1002. They are unhappy."
    result = run_case(claim, case_id="TEST-NO-CODE")
    assert result.escalated is True
    assert result.decision["rule_id"] == "R-NO-CODE"


def test_happy_path_reaches_a_decision_with_citations(cases):
    case = next(c for c in cases if c["expected_outcome"] == "approve_warranty")
    result = run_case(case["question"], case_id="TEST-HAPPY")
    assert result.decision["decision"] == "approve_warranty"
    assert result.escalated is False
    assert result.confidence >= 0.7
    assert any(chunk in result.justification for chunk in ("[",))  # citations present
    assert result.evidence, "evidence must be recorded"


def test_unsupported_citations_are_regenerated_then_rebuilt(cases):
    case = next(c for c in cases if c["expected_outcome"] == "approve_warranty")
    provider = LyingProvider()
    result = run_case(case["question"], case_id="TEST-CITATIONS", provider=provider)
    assert provider.calls >= 2, "the post-check must ask for a regeneration"
    assert "SOP-999" not in result.justification, "the invented citation must not survive"
    assert any(event["type"] == "citation_reject" for event in result.audit)


def test_missing_capability_data_fails_the_evidence_checkpoint(cases):
    case = next(c for c in cases if c["expected_outcome"] == "escalate" and not c["has_spc"])
    result = run_case(case["question"], case_id="TEST-NO-SPC")
    failures = [e for e in result.audit if e["type"] == "checkpoint" and not e["detail"].get("passed", True)]
    assert failures, "the evidence checkpoint should have failed at least once"
    assert result.escalated is True


def test_low_confidence_routes_to_a_human_even_when_a_rule_matched(cases):
    case = next(c for c in cases if c["expected_outcome"] == "approve_warranty")
    result = run_case(case["question"], case_id="TEST-THRESHOLD", confidence_threshold=0.99)
    assert result.decision["decision"] == "approve_warranty"
    assert result.escalated is True
    assert "below the 0.99 threshold" in result.escalation_reason


def test_audit_trail_is_written_to_disk(cases):
    case = cases[0]
    result = run_case(case["question"], case_id="TEST-AUDIT")
    assert result.audit_path.endswith("audit_TEST-AUDIT.json")
    from pathlib import Path

    assert Path(result.audit_path).exists()
    # every tool call must appear in the audit, not only in the result object
    tool_events = [e for e in result.audit if e["type"] == "tool_call"]
    assert len(tool_events) >= len(result.tool_calls) - 1


def test_unsafe_math_toggle_is_blocked_and_logged(cases):
    case = next(c for c in cases if c["defect_code"] == "DIM_OUT" and c["has_spc"])
    result = run_case(case["question"], case_id="TEST-GUARD", unsafe_llm_math=True)
    blocked = [e for e in result.audit if e["type"] == "guardrail_block"]
    assert blocked, "the model's estimate must be compared with the computed value"
    assert blocked[0]["detail"]["name"] == "capability_must_be_computed"
