"""Retrieval tests: the synthetic knowledge base must actually be searchable."""
from __future__ import annotations

from app.retrieval import get_kb


def test_corrosion_query_finds_the_warranty_section():
    hits = get_kb().search("is corrosion covered under warranty", k=5)
    assert hits, "no hits returned"
    doc_ids = [hit["doc_id"] for hit in hits]
    assert "POL-WAR-01" in doc_ids


def test_capability_query_finds_the_spc_handbook():
    hits = get_kb().search("process capability index cpk threshold", k=5)
    assert any(hit["doc_id"] == "STD-SPC-01" for hit in hits)


def test_supplier_query_finds_the_escalation_policy():
    hits = get_kb().search("supplier defect rate escalation SCAR", k=5)
    assert any(hit["doc_id"] == "POL-SUP-01" for hit in hits)


def test_scores_are_ordered_and_bounded():
    hits = get_kb().search("warranty claim evidence requirements", k=6)
    scores = [hit["score"] for hit in hits]
    assert scores == sorted(scores, reverse=True)
    assert all(score > 0 for score in scores)


def test_unknown_query_returns_nothing_rather_than_noise():
    assert get_kb().search("zzzzqqqq", k=3) == []
