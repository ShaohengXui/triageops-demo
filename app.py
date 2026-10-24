"""TriageOps — Streamlit UI.

Three tabs, each answering a different question a client actually asks:

    Run a case  -> what does the system do, and can I see why?
    Evaluation  -> does it work across the whole set, and what does it cost?
    Guardrails  -> what happens when the model is wrong?

Run:  streamlit run app.py
"""
from __future__ import annotations

import html
import json
from pathlib import Path

import streamlit as st

from app.agent import run_case, run_eval
from app.config import EVAL_CASES_PATH, SETTINGS
from app.llm import get_provider

st.set_page_config(page_title="TriageOps — staged-checkpoint agent", page_icon="◆", layout="wide")

CSS = """
<style>
  .block-container {padding-top: 2rem; max-width: 1200px;}
  .stage-card {border:1px solid #e3e3e3; border-radius:10px; padding:14px 16px; height:100%;
               background:#fcfcfc;}
  .stage-card.ok {border-left:4px solid #1f9d55;}
  .stage-card.fail {border-left:4px solid #d64545;}
  .stage-name {font-size:12px; letter-spacing:.08em; text-transform:uppercase; color:#777;}
  .stage-note {font-size:13px; color:#333; margin-top:6px; line-height:1.45;}
  .decision {font-size:30px; font-weight:600; letter-spacing:-.01em; margin:0;}
  .decision-sub {color:#666; font-size:13px; margin-top:4px;}
  .chip {background:#eef2f7; border:1px solid #d6dee8; border-radius:6px; padding:1px 7px;
         font-size:12px; font-family:ui-monospace, Consolas, monospace; color:#2b4a6f;}
  .guardrail {background:#fff4e5; border:1px solid #f0c48a; border-radius:8px; padding:10px 12px;
              font-size:13px; color:#7a4a00;}
  .evidence {font-size:13px; color:#333;}
  code {font-size:12px;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_cases() -> list[dict]:
    if not EVAL_CASES_PATH.exists():
        return []
    return json.loads(Path(EVAL_CASES_PATH).read_text(encoding="utf-8"))


def citation_markup(text: str) -> str:
    import re

    pattern = re.compile(r"\[([^\]\[]{2,80})\]")
    escaped = html.escape(text)
    return pattern.sub(lambda m: f'<span class="chip">{m.group(1)}</span>', escaped)


def render_timeline(stages: list[dict]) -> None:
    cols = st.columns(max(1, len(stages)))
    for col, stage in zip(cols, stages):
        status = stage.get("status", "running")
        css = "ok" if status == "passed" else ("fail" if status == "failed" else "")
        icon = {"passed": "✓", "failed": "✗"}.get(status, "…")
        note = " ".join(stage.get("notes", [])) or status
        col.markdown(
            f'<div class="stage-card {css}"><div class="stage-name">{stage["stage"]} {icon}</div>'
            f'<div class="stage-note">{html.escape(note)}</div></div>',
            unsafe_allow_html=True,
        )


def render_result(payload: dict, show_audit: bool = True) -> None:
    decision = payload["decision"]
    render_timeline(payload["stages"])
    st.write("")

    left, right = st.columns([2, 1])
    with left:
        label = decision.get("decision", "unknown").replace("_", " ")
        st.markdown(f'<p class="decision">{label}</p>', unsafe_allow_html=True)
        st.markdown(
            f'<p class="decision-sub">rule <code>{decision.get("rule_id", "")}</code> · '
            f'certainty {decision.get("certainty", 0)} · {len(payload["tool_calls"])} tool calls · '
            f'{payload["elapsed_ms"]} ms</p>',
            unsafe_allow_html=True,
        )
    with right:
        st.metric("Confidence", f"{payload['confidence']:.2f}")
        if payload["escalated"]:
            st.warning("Routed to a human reviewer", icon="⚠️")
        else:
            st.success("Auto-dispositioned", icon="✅")

    if payload["escalation_reason"]:
        st.info(payload["escalation_reason"], icon="ℹ")

    guardrails = [e for e in payload.get("audit", []) if e["type"] in ("guardrail_block", "citation_reject", "unsafe_override")]
    if guardrails:
        st.markdown("#### Guardrail events")
        for event in guardrails:
            st.markdown(
                f'<div class="guardrail"><b>{event["type"]}</b> @ {event["stage"]} — '
                f'{html.escape(json.dumps(event["detail"], default=str)[:300])}</div>',
                unsafe_allow_html=True,
            )

    st.markdown("#### Justification")
    st.markdown(
        f'<div class="evidence">{citation_markup(payload["justification"])}</div>',
        unsafe_allow_html=True,
    )

    st.markdown("#### Evidence")
    for item in payload["evidence"]:
        with st.expander(f'{item["type"]:<8} · {item["id"]}', expanded=False):
            st.code(item.get("summary", ""), language=None)
            if item["type"] == "document":
                st.caption(
                    "Source: synthetic knowledge base (data/docs). In production this would link to the "
                    "controlled document revision."
                )

    if show_audit:
        st.markdown("#### Audit trail")
        left, right = st.columns([3, 1])
        with right:
            st.download_button(
                "Download audit JSON",
                json.dumps(payload["audit"], indent=2, default=str),
                file_name=f'{payload["case_id"]}_audit.json',
                mime="application/json",
                width="stretch",
            )
        with left:
            st.caption(
                f"{len(payload['audit'])} events · saved as `{Path(payload['audit_path']).name}`"
            )
        with st.expander("Raw events", expanded=False):
            st.json(payload["audit"])


# --------------------------------------------------------------------------
# sidebar
# --------------------------------------------------------------------------
cases = load_cases()

st.sidebar.title("TriageOps")
st.sidebar.caption("Manufacturing quality triage agent · portfolio demo")

provider_choice = st.sidebar.selectbox(
    "LLM provider",
    options=["mock", "openai", "anthropic"],
    index=["mock", "openai", "anthropic"].index(SETTINGS.provider)
    if SETTINGS.provider in {"mock", "openai", "anthropic"} else 0,
    help="`mock` is a deterministic stub: no API key, no network. The pipeline is identical.",
)
threshold = st.sidebar.slider(
    "Confidence threshold for auto-disposition",
    min_value=0.30, max_value=0.95, value=float(SETTINGS.confidence_threshold), step=0.05,
    help="Below this the case is routed to a human instead of being decided.",
)
st.sidebar.divider()
if cases:
    st.sidebar.metric("Evaluation cases", len(cases))
    with st.sidebar.expander("Dataset"):
        st.write(
            "Synthetic: 6 suppliers · 12 parts · 40 work orders · 122 defect reports · "
            "510 SPC measurements · 8 procedure documents."
        )
        st.caption("Generated by scripts/seed_data.py with a fixed seed. No real data.")
else:
    st.sidebar.error("No dataset. Run `python scripts/seed_data.py`.")

if not cases:
    st.error("Dataset not found. Seed it first: `python scripts/seed_data.py`")
    st.stop()

provider = get_provider(provider_choice)

tab_run, tab_eval, tab_guard = st.tabs(["Run a case", "Evaluation", "Guardrails"])

# --------------------------------------------------------------------------
# tab 1 — run a case
# --------------------------------------------------------------------------
with tab_run:
    st.subheader("Run a claim through the pipeline")
    left, right = st.columns([1, 1])
    with left:
        case_ids = [case["case_id"] for case in cases]
        selected = st.selectbox("Evaluation case", case_ids, index=0)
        chosen = next(case for case in cases if case["case_id"] == selected)
        st.caption(
            f'{chosen["part_number"]} · {chosen["defect_code"]} · expected '
            f'`{chosen["expected_outcome"]}` (this is known because the case was generated from the rule engine)'
        )
    with right:
        free_text = st.text_area(
            "…or paste your own claim",
            height=110,
            placeholder="Customer claims corrosion on NX-1042, work order WO-1004, shipped 2025-11-02.",
        )

    question = free_text.strip() or chosen["question"]
    case_id = "CASE-LIVE" if free_text.strip() else chosen["case_id"]

    if st.button("Run pipeline", type="primary"):
        with st.spinner("Running"):
            result = run_case(
                question,
                case_id=case_id,
                provider=provider,
                confidence_threshold=threshold,
            )
        st.session_state["last_result"] = result.as_dict()
        st.session_state["last_question"] = question

    if "last_result" in st.session_state:
        st.caption(st.session_state.get("last_question", "")[:400])
        render_result(st.session_state["last_result"])
    else:
        st.info("Pick a case and press **Run pipeline**. The timeline fills in stage by stage.")

# --------------------------------------------------------------------------
# tab 2 — evaluation
# --------------------------------------------------------------------------
with tab_eval:
    st.subheader("Evaluation over all cases")
    st.caption(
        "The expected outcome for each case was produced by the same deterministic rule engine, so this "
        "measures whether the pipeline reaches the policy answer — a consistency check, not a proxy for "
        "real-world accuracy."
    )
    if st.button("Run all cases", type="primary"):
        with st.spinner("Running 20 cases"):
            st.session_state["eval_report"] = run_eval(cases, provider)

    report = st.session_state.get("eval_report")
    if report:
        metrics = report["metrics"]
        cols = st.columns(6)
        cols[0].metric("Decision match", f'{metrics["decision_match_pct"]}%')
        cols[1].metric("Escalation rate", f'{metrics["escalation_rate_pct"]}%')
        cols[2].metric("Avg tool calls", metrics["avg_tool_calls"])
        cols[3].metric("Checkpoint failures", metrics["checkpoint_failures"])
        cols[4].metric("Avg latency", f'{metrics["avg_latency_ms"]} ms')
        cols[5].metric("Cost / 20 cases", f'${metrics["estimated_cost_usd"]:.4f}')

        st.dataframe(
            [
                {
                    "case": row["case_id"],
                    "defect": row["defect_code"],
                    "expected": row["expected"],
                    "actual": row["actual"],
                    "match": "✓" if row["match"] else "✗",
                    "rule": row["rule"],
                    "confidence": row["confidence"],
                    "tools": row["tool_calls"],
                }
                for row in report["rows"]
            ],
            width="stretch",
            hide_index=True,
        )
        st.caption(
            f'provider `{metrics["provider"]}` · {metrics["total_tokens"]} tokens · '
            f'{metrics["guardrail_blocks"]} guardrail blocks'
        )
    else:
        st.info("Press **Run all cases** to produce the table.")

# --------------------------------------------------------------------------
# tab 3 — guardrails
# --------------------------------------------------------------------------
with tab_guard:
    st.subheader("Break it on purpose")
    st.caption(
        "Clients do not lose money when a model is clever. They lose money when it is confidently wrong "
        "and nobody can trace why. These switches disable one protection at a time so you can see the "
        "validator catch it."
    )
    col1, col2 = st.columns(2)
    with col1:
        llm_math = st.toggle(
            "Let the LLM compute the capability index",
            value=False,
            help="When on, the model's estimate is compared with the value computed in Python. "
                 "A disagreement is blocked and the computed value is used.",
        )
    with col2:
        skip_check = st.toggle(
            "Skip the evidence checkpoint",
            value=False,
            help="When on, a case with missing evidence is allowed to proceed. The audit trail marks it unsafe.",
        )

    case_ids = [case["case_id"] for case in cases]
    # Default to a case whose disposition depends on a measured capability value, so
    # the "let the model do the math" switch has something to disagree about.
    preferred = next(
        (i for i, c in enumerate(cases) if c["defect_code"] == "DIM_OUT" and c["has_spc"]),
        0,
    )
    guard_case = st.selectbox("Case to run", case_ids, index=preferred, key="guard_case")
    guard_question = next(case for case in cases if case["case_id"] == guard_case)["question"]

    if st.button("Run with these settings", type="primary"):
        if llm_math or skip_check:
            st.warning(
                "Unsafe demo mode — " + ", ".join(
                    [n for n, on in (("capability estimated by the model", llm_math),
                                     ("evidence checkpoint skipped", skip_check)) if on]
                ),
                icon="🧪",
            )
        result = run_case(
            guard_question,
            case_id=f"{guard_case}-GUARD",
            provider=provider,
            confidence_threshold=threshold,
            unsafe_llm_math=llm_math,
            unsafe_skip_checkpoint=skip_check,
        )
        render_result(result.as_dict(), show_audit=True)

    st.divider()
    st.markdown("#### What each protection is for")
    st.markdown(
        "- **Capability is computed, never generated.** `spc_metrics` does the arithmetic in Python; the "
        "model may only describe the result. A plausible-looking Cpk is worse than no Cpk.\n"
        "- **Evidence before decision.** The evidence stage cannot complete without a document source and a "
        "production record, and measurement-dependent codes additionally require a capability record.\n"
        "- **Citations are validated.** Every `[id]` in the justification must exist in the evidence set, or "
        "the text is regenerated once and then rebuilt from the evidence.\n"
        "- **Uncertainty escalates.** Confidence below the threshold routes to a human with the evidence "
        "attached, and the audit trail keeps the reason."
    )
