"""The rule engine is the part that must never drift.

These tests pin the policy behaviour: coverage first, then defect validity, then
manufacturing evidence.
"""
from __future__ import annotations

from app.rules import APPROVE, ESCALATE, REJECT, REWORK, cpk, decide


def _decide(**overrides):
    base = dict(
        part_number="NX-1042",
        defect_code="CORROSION",
        warranty_months=24,
        age_days=100,
        cpk_value=None,
    )
    base.update(overrides)
    return decide(**base)


def test_coverage_is_evaluated_before_the_defect_mode():
    # Even a normally coverable corrosion claim is rejected once out of warranty.
    result = _decide(age_days=800)
    assert result.decision == REJECT
    assert result.rule_id == "R-WAR-EXPIRED"


def test_corrosion_inside_the_automatic_window_is_approved():
    result = _decide(age_days=200)
    assert result.decision == APPROVE
    assert result.rule_id == "R-CORR-COVERED"


def test_corrosion_on_a_short_warranty_part_escalates():
    result = _decide(warranty_months=12, age_days=200)
    assert result.decision == ESCALATE
    assert result.rule_id == "R-CORR-BOUNDARY"


def test_corrosion_outside_the_twelve_month_window_escalates():
    result = _decide(warranty_months=24, age_days=500)
    assert result.decision == ESCALATE
    assert result.rule_id == "R-CORR-BOUNDARY"


def test_measurement_code_without_capability_data_escalates():
    result = _decide(defect_code="DIM_OUT", cpk_value=None)
    assert result.decision == ESCALATE
    assert result.rule_id == "R-NO-SPC"
    assert "SPC capability record" in result.needs


def test_marginal_capability_leads_to_rework():
    result = _decide(defect_code="DIM_OUT", cpk_value=1.10)
    assert result.decision == REWORK
    assert result.rule_id == "R-CPK-MARGINAL"


def test_capable_process_does_not_support_a_manufacturing_claim():
    result = _decide(defect_code="DIM_OUT", cpk_value=1.62)
    assert result.decision == REJECT
    assert result.rule_id == "R-CPK-CAPABLE"


def test_crack_always_requires_engineering_review():
    result = _decide(defect_code="CRACK", cpk_value=0.9)
    assert result.decision == ESCALATE
    assert result.rule_id == "R-CRACK-ENG"


def test_electrical_failures_escalate_on_unknown_cause():
    result = _decide(defect_code="ELECTRICAL", age_days=30)
    assert result.decision == ESCALATE
    assert result.rule_id == "R-ELEC-CAUSE"


def test_surface_defects_are_reworkable_not_warranty():
    result = _decide(defect_code="SURFACE", age_days=30)
    assert result.decision == REWORK
    assert result.rule_id == "R-SURFACE-REWORK"


def test_high_supplier_defect_rate_escalates():
    result = _decide(defect_code="LEAK", age_days=30, supplier_defect_rate=3.4)
    assert result.decision == ESCALATE
    assert result.rule_id == "R-SUP-RATE"


# --- capability arithmetic ------------------------------------------------
def test_cpk_is_symmetric_around_the_mean():
    assert cpk(mean=10.0, std=1.0, usl=14.0, lsl=6.0) == 1.333


def test_cpk_uses_the_tighter_side():
    # Upper limit is much closer to the mean, so it governs.
    assert cpk(mean=10.0, std=1.0, usl=11.5, lsl=0.0) == 0.5


def test_cpk_refuses_degenerate_input():
    assert cpk(mean=10.0, std=0.0, usl=12.0, lsl=8.0) is None
    assert cpk(mean=10.0, std=1.0, usl=None, lsl=8.0) is None
