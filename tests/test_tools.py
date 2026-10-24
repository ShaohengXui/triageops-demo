"""Tool-level tests: argument validation stays strict, and capability is computed."""
from __future__ import annotations

import pytest

from app import tools
from app.tools import ToolValidationError


def test_unknown_tool_is_rejected():
    with pytest.raises(ToolValidationError):
        tools.validate("drop_tables", {})


def test_unknown_argument_is_rejected():
    with pytest.raises(ToolValidationError):
        tools.validate("query_orders", {"work_order_id": "WO-1001", "sql": "SELECT 1"})


def test_wrong_argument_type_is_rejected():
    with pytest.raises(ToolValidationError):
        tools.validate("search_docs", {"query": "corrosion", "k": "four"})


def test_tool_not_permitted_in_stage_is_rejected():
    with pytest.raises(ToolValidationError):
        tools.validate("search_docs", {"query": "corrosion"}, allowed={"warranty_rules"})


def test_missing_argument_is_rejected():
    with pytest.raises(ToolValidationError):
        tools.validate("spc_metrics", {})


def test_spc_metrics_are_computed_in_code():
    result = tools.call("spc_metrics", {"work_order_id": "WO-1002"})
    data = result["data"]
    assert data["available"] is True
    assert data["computed_by"] == "python (not the model)"
    assert isinstance(data["cpk"], float)
    # mean and std must be internally consistent with the returned cpk
    expected = (data["usl"] - data["mean"]) / (3 * data["std"])
    lower = (data["mean"] - data["lsl"]) / (3 * data["std"])
    assert data["cpk"] == pytest.approx(min(expected, lower), abs=1e-2)


def test_spc_metrics_report_missing_data_instead_of_guessing():
    result = tools.call("spc_metrics", {"work_order_id": "WO-9999"})
    assert result["data"]["available"] is False
    assert result["sources"] == []


def test_rules_use_the_claimed_work_order_not_the_latest_one():
    """Regression test.

    The first version resolved the part's newest work order, so an expired claim
    was silently evaluated against a fresh production run and approved. The
    evaluation set surfaced it; this test keeps it fixed.
    """
    from app import db

    rows = db.query(
        "SELECT wo.id, wo.started_at, p.warranty_months FROM work_orders wo "
        "JOIN parts p ON p.part_number = wo.part_number WHERE wo.part_number = 'NX-1042' "
        "ORDER BY wo.started_at ASC"
    )
    oldest, newest = rows[0], rows[-1]
    assert oldest["id"] != newest["id"]

    old_result = tools.call(
        "warranty_rules",
        {"part_number": "NX-1042", "defect_code": "CORROSION", "work_order_id": oldest["id"]},
    )["data"]
    new_result = tools.call(
        "warranty_rules",
        {"part_number": "NX-1042", "defect_code": "CORROSION", "work_order_id": newest["id"]},
    )["data"]

    assert old_result["age_days"] > new_result["age_days"]
    assert old_result["rule_id"] != new_result["rule_id"]


def test_open_case_defaults_to_dry_run():
    result = tools.call("open_case", {"summary": "x", "decision": "approve_warranty", "evidence": ["a"]})
    assert result["data"]["dry_run"] is True
