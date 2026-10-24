"""Deterministic business rules.

The whole point of this module: the *decision* is computed here, in plain Python,
with no model involvement. The LLM is only allowed to explain a decision this
module already made. Tests in tests/test_rules.py pin the behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Decisions the system can produce.
APPROVE = "approve_warranty"
REJECT = "reject_warranty"
REWORK = "rework"
ESCALATE = "escalate"

ALLOWED_DECISIONS = (APPROVE, REJECT, REWORK, ESCALATE)

# Defect codes whose disposition depends on measurement data.
MEASUREMENT_CODES = ("DIM_OUT", "CRACK")


def cpk(mean: float, std: float, usl: float, lsl: float) -> float | None:
    """Process capability index. Returns None when it cannot be computed.

    Deliberately plain arithmetic: this number must be reproducible and auditable,
    which is exactly why it is not asked of a language model.
    """
    if std is None or std <= 0:
        return None
    if usl is None or lsl is None:
        return None
    upper = (usl - mean) / (3.0 * std)
    lower = (mean - lsl) / (3.0 * std)
    return round(min(upper, lower), 3)


@dataclass
class RuleResult:
    decision: str
    rule_id: str
    certainty: float
    reasons: list[str] = field(default_factory=list)
    needs: list[str] = field(default_factory=list)  # evidence still required

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "rule_id": self.rule_id,
            "certainty": self.certainty,
            "reasons": self.reasons,
            "needs": self.needs,
        }


def decide(
    *,
    part_number: str,
    defect_code: str,
    warranty_months: int,
    age_days: int,
    cpk_value: float | None,
    supplier_defect_rate: float | None = None,
) -> RuleResult:
    """Evaluate the policies in data/docs against the facts of one case.

    Order matters and mirrors CLA-CUS-01 "Evaluation order": coverage first,
    then defect validity, then manufacturing evidence. Evaluating coverage first
    avoids an expensive engineering investigation on an out-of-warranty part.
    """
    warranty_days = warranty_months * 30

    # 1. Coverage window (POL-WAR-01 "Coverage period").
    if age_days > warranty_days:
        return RuleResult(
            decision=REJECT,
            rule_id="R-WAR-EXPIRED",
            certainty=0.95,
            reasons=[
                f"Shipment age {age_days} days exceeds the {warranty_months}-month "
                f"({warranty_days}-day) coverage period for {part_number}."
            ],
        )

    # 2. Corrosion handling (POL-WAR-01 "Corrosion defects").
    if defect_code == "CORROSION":
        if warranty_months >= 18 and age_days <= 365:
            return RuleResult(
                decision=APPROVE,
                rule_id="R-CORR-COVERED",
                certainty=0.90,
                reasons=[
                    f"Corrosion is a covered mode for parts with an 18-month-or-longer warranty; "
                    f"{part_number} carries {warranty_months} months.",
                    f"Claim age {age_days} days is inside the 12-month automatic approval window.",
                ],
            )
        return RuleResult(
            decision=ESCALATE,
            rule_id="R-CORR-BOUNDARY",
            certainty=0.60,
            reasons=[
                "Corrosion claim falls in the boundary window: inside warranty but outside the "
                "12-month automatic approval window, or the part warranty is shorter than 18 months.",
                "POL-WAR-01 requires an engineer to separate a coating/material failure (covered) "
                "from environmental exposure (excluded).",
            ],
            needs=["engineering disposition"],
        )

    # 3. Measurement-dependent codes (STD-SPC-01 + CAT-DEF-01).
    if defect_code in MEASUREMENT_CODES:
        if cpk_value is None:
            return RuleResult(
                decision=ESCALATE,
                rule_id="R-NO-SPC",
                certainty=0.40,
                reasons=[
                    f"{defect_code} disposition depends on the capability record, and no usable "
                    "SPC capability value exists for this production window.",
                    "Deciding without the capability record would be a guess.",
                ],
                needs=["SPC capability record"],
            )
        if defect_code == "CRACK":
            return RuleResult(
                decision=ESCALATE,
                rule_id="R-CRACK-ENG",
                certainty=0.70,
                reasons=[
                    "CAT-DEF-01 and SOP-QMS-01 require engineering review for any CRACK before "
                    "disposition; crack is never use-as-is or rework.",
                ],
                needs=["engineering review"],
            )
        if cpk_value < 1.33:
            return RuleResult(
                decision=REWORK,
                rule_id="R-CPK-MARGINAL",
                certainty=0.85,
                reasons=[
                    f"Measured Cpk {cpk_value} is below the 1.33 capability threshold (STD-SPC-01).",
                    "A marginal capability record supports a manufacturing cause, so the lot is "
                    "dispositioned as rework rather than accepted.",
                ],
            )
        return RuleResult(
            decision=REJECT,
            rule_id="R-CPK-CAPABLE",
            certainty=0.80,
            reasons=[
                f"Measured Cpk {cpk_value} is at or above 1.33, so the process was capable during "
                "this production window and a manufacturing cause is not supported.",
            ],
        )

    # 4. Cosmetic (CAT-DEF-01 "Cosmetic and surface codes").
    if defect_code == "SURFACE":
        return RuleResult(
            decision=REWORK,
            rule_id="R-SURFACE-REWORK",
            certainty=0.75,
            reasons=["Surface defects are reworkable under STD-REW-01 and are not warranty-approvable."],
        )

    # 5. Electrical (POL-WAR-01 "Exclusions").
    if defect_code == "ELECTRICAL":
        return RuleResult(
            decision=ESCALATE,
            rule_id="R-ELEC-CAUSE",
            certainty=0.55,
            reasons=[
                "Electrical components are covered only for manufacturing defects; the failure "
                "cause cannot be established from the record alone.",
            ],
            needs=["failure analysis"],
        )

    # 6. Supplier-driven escalation (POL-SUP-01).
    if supplier_defect_rate is not None and supplier_defect_rate > 2.0:
        return RuleResult(
            decision=ESCALATE,
            rule_id="R-SUP-RATE",
            certainty=0.65,
            reasons=[
                f"Supplier defect rate {supplier_defect_rate} per thousand is above the 2 per thousand "
                "threshold that triggers supplier escalation.",
            ],
            needs=["supplier corrective action"],
        )

    return RuleResult(
        decision=ESCALATE,
        rule_id="R-UNCLASSIFIED",
        certainty=0.35,
        reasons=[f"No automatic disposition rule covers defect code {defect_code}."],
        needs=["manual disposition"],
    )
