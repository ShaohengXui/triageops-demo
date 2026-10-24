"""Synthetic knowledge base for the demo.

Every sentence here is written for this portfolio demo. No real company, product,
supplier or procedure is represented. A fixed document set is used (instead of
randomly generated prose) so retrieval evaluation is reproducible.
"""
from __future__ import annotations

DOCUMENTS: list[dict] = [
    {
        "doc_id": "SOP-QMS-01",
        "title": "Quality Management SOP",
        "sections": [
            (
                "Scope and applicability",
                [
                    "This procedure applies to all manufactured parts produced on lines L1 through L4, "
                    "including incoming components, in-process assemblies and finished goods. It defines how "
                    "a nonconformance is raised, contained, dispositioned and closed.",
                    "A nonconformance exists whenever a characteristic does not meet the drawing, the control "
                    "plan or the customer specification. Defects identified after shipment are handled under "
                    "CLA-CUS-01 and, where a warranty is claimed, under POL-WAR-01.",
                ],
            ),
            (
                "Raising a nonconformance",
                [
                    "Any operator, inspector or quality technician may raise a nonconformance report (NCR). "
                    "The report must reference the work order, the defect code from CAT-DEF-01, the quantity "
                    "affected, the shift and the measurement or inspection method used.",
                    "The NCR is raised within the same shift the defect is found. A defect found in a later "
                    "shift is recorded against the shift in which it was detected, not the shift that produced "
                    "the material, because the containment timing depends on detection.",
                ],
            ),
            (
                "Containment",
                [
                    "Containment must be completed within four hours of the NCR being raised. It consists of "
                    "quarantining suspect material in the hold area, tagging it with the NCR number, and "
                    "sweeping the downstream buffers back to the last known-good checkpoint.",
                    "Containment does not require root cause. Root cause analysis is owned by the CAPA process "
                    "in PRO-CAPA-01 and may take several weeks. The purpose of containment is to stop the "
                    "defect from reaching the customer while analysis proceeds.",
                ],
            ),
            (
                "Material review board",
                [
                    "The MRB dispositions held material as one of: use-as-is, rework, repair, scrap, or return "
                    "to supplier. Use-as-is and repair require engineering sign-off because both permanently "
                    "accept a deviation from the drawing.",
                    "Rework follows STD-REW-01. Material returned to a supplier is tracked under POL-SUP-01 "
                    "and is scored against the supplier's defect rate the same way an incoming rejection is.",
                ],
            ),
            (
                "Records and retention",
                [
                    "NCRs, measurement records and disposition evidence are retained for seven years. "
                    "Measurement data is retained in the SPC system rather than in the NCR, and the NCR stores "
                    "only the reference, so that a later capability study can re-read the raw values.",
                ],
            ),
        ],
    },
    {
        "doc_id": "POL-WAR-01",
        "title": "Warranty Policy",
        "sections": [
            (
                "Coverage period",
                [
                    "Parts carry a warranty period stated on the part record, typically 12, 18 or 24 months from "
                    "the shipment date. The shipment date is the work order completion date recorded in the "
                    "production system, not the date the customer installed the part.",
                    "A claim received within the coverage period is eligible for evaluation. A claim received "
                    "after the coverage period expires is rejected as out of warranty unless a documented "
                    "safety-related defect applies, in which case the claim is escalated for management review.",
                ],
            ),
            (
                "Corrosion defects",
                [
                    "Corrosion is a covered defect mode for parts with a warranty period of 18 months or longer, "
                    "provided the claim is received within 12 months of shipment. Corrosion claims within that "
                    "window are approved subject to visual confirmation and a check that the defect is not on "
                    "the exclusion list.",
                    "Corrosion claims received after 12 months but still inside the warranty period are not "
                    "automatically approved. They are escalated so that an engineer can decide whether the "
                    "corrosion is a material or coating failure, which is covered, or environmental exposure, "
                    "which is not.",
                ],
            ),
            (
                "Exclusions",
                [
                    "The following are excluded from warranty coverage: damage caused by improper installation, "
                    "damage caused by modification or repair performed by a third party, consumable components, "
                    "and cosmetic surface finish wear that does not affect function.",
                    "Electrical components are covered only for manufacturing defects; field failures caused by "
                    "overvoltage, reverse polarity or ingress after installation are excluded. Where the failure "
                    "mode cannot be established from the returned part, the claim is escalated rather than "
                    "rejected.",
                ],
            ),
            (
                "Claim evidence requirements",
                [
                    "Every claim must include the part number, the work order reference if available, the "
                    "shipment date, photographs of the defect, and the customer's description of the failure "
                    "conditions. A claim missing the shipment date cannot be evaluated against the coverage "
                    "period and is returned to the customer rather than guessed at.",
                    "Where a dimensional or process-related failure is alleged, the reviewer must also consult "
                    "the SPC record for the production window. A capability study is the primary evidence for "
                    "deciding between a manufacturing cause and a service cause.",
                ],
            ),
            (
                "Approval authority",
                [
                    "Claims under 500 units of value may be approved by the quality engineer. Claims above that "
                    "value require quality manager approval. Any claim that is ambiguous under this policy is "
                    "escalated with the evidence attached; the reviewer does not decide on incomplete evidence.",
                ],
            ),
        ],
    },
    {
        "doc_id": "CAT-DEF-01",
        "title": "Defect Code Catalog",
        "sections": [
            (
                "How codes are used",
                [
                    "Every defect report carries exactly one code from this catalog. The code drives the "
                    "disposition rules, the warranty eligibility in POL-WAR-01 and the supplier scoring in "
                    "POL-SUP-01, so a wrong code has downstream effects beyond the report itself.",
                    "When two defect modes are present, the code describing the primary failure mechanism is "
                    "used and the secondary mode is recorded in the description field.",
                ],
            ),
            (
                "Cosmetic and surface codes",
                [
                    "SURFACE: scratch, scuff, stain or finish defect that does not affect function or "
                    "dimensional conformance. SURFACE defects are generally reworkable under STD-REW-01 and are "
                    "not warranty-approvable unless the customer specification defines the surface as functional.",
                    "CORROSION: oxidation, pitting or coating breakdown visible to the naked eye. Corrosion is "
                    "treated as a material or process defect for warranty purposes; it is never classed as "
                    "cosmetic regardless of appearance.",
                ],
            ),
            (
                "Dimensional and structural codes",
                [
                    "DIM_OUT: a measured characteristic outside the drawing tolerance. DIM_OUT requires the "
                    "measurement record to be cited, and its disposition depends on the process capability "
                    "record under STD-SPC-01.",
                    "CRACK: a fracture or incipient fracture in the material. CRACK is always at least severity "
                    "high, is never use-as-is, and requires engineering review before any disposition.",
                ],
            ),
            (
                "Functional and assembly codes",
                [
                    "LEAK: failure of a pressure or fluid boundary. LEAK requires a documented test method "
                    "because the disposition depends on whether the leak was found under test pressure or in "
                    "service.",
                    "DELAM: separation between bonded layers. THREAD: damaged, missing or out-of-spec thread. "
                    "ELECTRICAL: open, short or insulation failure. ELECTRICAL defects are subject to the "
                    "exclusion rules in POL-WAR-01 and are escalated when the failure cause is not established.",
                ],
            ),
        ],
    },
    {
        "doc_id": "PRO-CAPA-01",
        "title": "Corrective and Preventive Action Procedure",
        "sections": [
            (
                "When a CAPA is required",
                [
                    "A CAPA is mandatory for any defect of severity high or critical, for any defect that "
                    "reaches a customer, and for any defect code that repeats three or more times on the same "
                    "part within 90 days.",
                    "A CAPA is not required for an isolated low-severity defect that was contained before "
                    "shipment; those are recorded and trended instead.",
                ],
            ),
            (
                "Root cause analysis",
                [
                    "Root cause analysis uses a structured method: 5-whys for simple causation, a fishbone for "
                    "multi-factor problems, and a fault tree where the failure could have more than one "
                    "independent trigger. The chosen method and the evidence for the root cause are recorded in "
                    "the CAPA record.",
                    "The most common analytical failure is stopping at the operator error level. The CAPA is "
                    "not accepted until the analysis explains why the process permitted the error.",
                ],
            ),
            (
                "Effectiveness verification",
                [
                    "Every corrective action is verified after 30 days of production. Verification requires data: "
                    "the defect rate for the affected code on the affected part, compared with the rate before "
                    "the action. A CAPA closed without data is re-opened at the next audit.",
                ],
            ),
            (
                "Link to supplier actions",
                [
                    "Where the root cause is attributed to purchased material, the CAPA is linked to a supplier "
                    "corrective action request under POL-SUP-01 and both records reference each other so that "
                    "the supplier's response can be audited later.",
                ],
            ),
        ],
    },
    {
        "doc_id": "POL-SUP-01",
        "title": "Supplier Escalation",
        "sections": [
            (
                "Scoring",
                [
                    "Each supplier is scored monthly on on-time delivery, incoming defect rate and responsiveness "
                    "to corrective action requests. The incoming defect rate is defects per thousand received "
                    "units, not defects per lot, so that a large clean lot cannot hide a small bad one.",
                    "A supplier with an on-time rate below 90 percent or a defect rate above 2 percent enters "
                    "the escalation process.",
                ],
            ),
            (
                "Escalation steps",
                [
                    "Step one is a supplier corrective action request (SCAR) with a 10 working day response "
                    "deadline. Step two, triggered by a repeat SCAR or an inadequate response, is a containment "
                    "requirement: 100 percent incoming inspection at the supplier's cost until three consecutive "
                    "clean lots.",
                    "Step three is a quality audit, either on site or remote, and step four is removal from the "
                    "approved supplier list. Steps one and two are automatic; steps three and four require "
                    "purchasing and quality management agreement.",
                ],
            ),
            (
                "When to escalate immediately",
                [
                    "A defect that creates a safety risk, or a shipment found to contain a defect mode that the "
                    "supplier previously certified as corrected, skips directly to step two regardless of the "
                    "monthly score.",
                ],
            ),
        ],
    },
    {
        "doc_id": "STD-SPC-01",
        "title": "SPC and Process Capability Handbook",
        "sections": [
            (
                "Capability indices",
                [
                    "Process capability is reported as Cpk, computed from the process mean and standard deviation "
                    "against the specification limits. Cpk of 1.33 or greater is considered capable. Cpk between "
                    "1.00 and 1.33 is marginal and requires a monitoring plan. Cpk below 1.00 is not capable and "
                    "the lot is not releasable without disposition.",
                    "Capability must be computed from measurements, never estimated. These calculations are "
                    "performed in code by the measurement system; they are not delegated to a language model, "
                    "because a plausible-looking number is worse than no number.",
                ],
            ),
            (
                "Sampling",
                [
                    "Sampling frequency is defined per part in the control plan, typically five pieces per hour "
                    "on a running process and a full first-article inspection at setup. A setup that does not "
                    "have a completed first-article inspection cannot release production.",
                ],
            ),
            (
                "Out-of-control signals",
                [
                    "The process is out of control if any point falls outside the control limits, if seven "
                    "consecutive points fall on one side of the mean, or if six points trend in one direction. "
                    "An out-of-control process is investigated even when every individual measurement is inside "
                    "the specification, because the trend predicts the next failure.",
                ],
            ),
            (
                "What capability means for a claim",
                [
                    "A lot produced by a process with Cpk below 1.33 has a documented elevated risk of "
                    "dimensional nonconformance. In a warranty dispute over a DIM_OUT or CRACK defect, a marginal "
                    "capability record supports a manufacturing cause rather than a customer-use cause.",
                ],
            ),
        ],
    },
    {
        "doc_id": "STD-REW-01",
        "title": "Rework Standard",
        "sections": [
            (
                "Authorization",
                [
                    "Rework requires a written rework instruction that states the operation, the acceptance "
                    "criteria after rework, and the inspection method. Rework performed without an instruction "
                    "is treated as an unapproved process change.",
                    "Rework is not permitted on cracked or fractured material, on safety-critical characteristics, "
                    "or where the cumulative material removal would take the part below the minimum wall "
                    "thickness. Those cases go to engineering for repair disposition or scrap.",
                ],
            ),
            (
                "Re-inspection",
                [
                    "Every reworked part is re-inspected to the full characteristic set, not only to the "
                    "characteristic that was reworked, because rework introduces new stress and handling risk. "
                    "The re-inspection record is attached to the NCR.",
                ],
            ),
            (
                "Cost and traceability",
                [
                    "Rework hours are charged to the responsible cost centre and are reported weekly alongside "
                    "scrap. Rework is a symptom of an uncontrolled process, so a rising rework rate is treated as "
                    "a process signal, not merely as an accounting line.",
                ],
            ),
        ],
    },
    {
        "doc_id": "CLA-CUS-01",
        "title": "Customer Claims Handling",
        "sections": [
            (
                "Intake",
                [
                    "A customer claim is logged within one business day of receipt with the customer reference, "
                    "the part number, the quantity, the claimed defect mode and the supporting evidence. The "
                    "initial response to the customer is due within two business days and the substantive "
                    "position within five business days.",
                    "If the evidence is insufficient to reach a position, the five-day clock is met with an "
                    "interim response that states exactly which documents are needed. Silence is not an "
                    "acceptable response.",
                ],
            ),
            (
                "Evaluation order",
                [
                    "Claims are evaluated in a fixed order: coverage under POL-WAR-01, then defect code validity "
                    "under CAT-DEF-01, then manufacturing evidence under STD-SPC-01 and the production record. "
                    "Evaluating in this order prevents an expensive engineering investigation on a part that is "
                    "simply out of warranty.",
                ],
            ),
            (
                "Escalation to a human",
                [
                    "A claim is escalated when the defect mode cannot be confirmed from the evidence, when the "
                    "coverage period boundary is ambiguous, when the claimed value exceeds the engineer's "
                    "authority, or when the evidence supports two different dispositions. Escalation records the "
                    "reason and the evidence collected so far; it is a legitimate outcome, not a failure.",
                ],
            ),
            (
                "Feedback into quality",
                [
                    "Every approved claim generates a defect report against the originating work order so that "
                    "field failures appear in the same defect rate the plant is measured on. Without this step, "
                    "escapes look like good quality performance on paper.",
                ],
            ),
        ],
    },
]
