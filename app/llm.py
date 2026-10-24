"""LLM providers.

Three task-specific methods instead of one generic "chat" call, so the agent's
control flow cannot depend on the free-form shape of a prompt answer:

    classify_case(question)             -> structured intake
    choose_tool(state)                  -> one typed tool call
    write_justification(decision, evid) -> prose, must cite evidence ids

`MockProvider` implements the same interface deterministically with no network.
It is not a fake model pretending to be smart: it is a scripted stand-in that
exercises the identical pipeline, which is what makes the demo runnable offline.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from .config import SETTINGS

DEFECT_KEYWORDS = {
    "CORROSION": ["corrosion", "corroded", "rust", "pitting", "oxidation"],
    "SURFACE": ["scratch", "surface", "cosmetic", "scuff", "stain"],
    "DIM_OUT": ["dimension", "dimensional", "dim out", "dim_out", "tolerance", "out of spec",
                "oversize", "undersize", "oversized", "undersized"],
    "CRACK": ["crack", "fracture", "split"],
    "LEAK": ["leak", "seep", "pressure loss"],
    "DELAM": ["delamination", "delam", "layer separation"],
    "THREAD": ["thread", "threads", "stripped"],
    "ELECTRICAL": ["electrical", "short", "open circuit", "insulation", "voltage"],
}


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def merge(self, other: "Usage") -> "Usage":
        return Usage(
            self.prompt_tokens + other.prompt_tokens,
            self.completion_tokens + other.completion_tokens,
        )


class BaseProvider:
    name = "base"

    def __init__(self) -> None:
        self.usage = Usage()

    # -- helpers --------------------------------------------------------
    def _track(self, prompt: str, completion: str) -> None:
        self.usage = self.usage.merge(
            Usage(max(1, len(prompt) // 4), max(1, len(completion) // 4))
        )

    # -- interface ------------------------------------------------------
    def classify_case(self, question: str) -> dict[str, Any]:
        raise NotImplementedError

    def choose_tool(self, state: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def write_justification(self, decision: dict[str, Any], evidence: list[dict]) -> str:
        raise NotImplementedError


class MockProvider(BaseProvider):
    """Deterministic stand-in. Same interface, zero network."""

    name = "mock"

    def classify_case(self, question: str) -> dict[str, Any]:
        text = question.lower()
        work_order = None
        match = re.search(r"\b(wo-\d{4})\b", text)
        if match:
            work_order = match.group(1).upper()
        if not work_order:
            match = re.search(r"\b(\d{4})\b", text)
            if match:
                work_order = f"WO-{match.group(1)}"

        defect = None
        for code, words in DEFECT_KEYWORDS.items():
            if any(word in text for word in words):
                defect = code
                break

        quantity = None
        match = re.search(r"quantity\s+(\d+)", text)
        if match:
            quantity = int(match.group(1))

        category = "product_defect"
        if "supplier" in text or "scar" in text:
            category = "supplier_issue"
        elif "policy" in text or "procedure" in text or "how do we" in text:
            category = "policy_question"

        payload = {
            "category": category,
            "work_order_id": work_order,
            "defect_code": defect,
            "quantity": quantity,
            "reasoning": "keyword extraction over the claim text (mock provider)",
        }
        self._track(question, json.dumps(payload))
        return payload

    def choose_tool(self, state: dict[str, Any]) -> dict[str, Any]:
        defect = state.get("defect_code") or "CORROSION"
        part = state.get("part_number")
        work_order = state.get("work_order_id")
        done = state.get("called", [])

        def called(tool: str) -> bool:
            return any(c["tool"] == tool for c in done)

        if not called("search_docs"):
            query = f"{defect.replace('_', ' ')} warranty coverage disposition"
            return {"tool": "search_docs", "args": {"query": query, "k": 4}}

        if not called("query_orders") and work_order:
            return {"tool": "query_orders", "args": {"work_order_id": work_order}}

        if not called("defect_history") and part:
            return {"tool": "defect_history", "args": {"part_number": part, "limit": 10}}

        if defect in ("DIM_OUT", "CRACK") and not called("spc_metrics") and work_order:
            return {"tool": "spc_metrics", "args": {"work_order_id": work_order}}

        if not called("warranty_rules") and part:
            args = {"part_number": part, "defect_code": defect}
            if work_order:
                args["work_order_id"] = work_order
            return {"tool": "warranty_rules", "args": args}

        return {"tool": "finish", "args": {"reason": "evidence sufficient"}}

    def write_justification(self, decision: dict[str, Any], evidence: list[dict]) -> str:
        ids = [e["id"] for e in evidence if e.get("id")]
        head = {
            "approve_warranty": "The claim is approved under warranty.",
            "reject_warranty": "The claim is rejected.",
            "rework": "The material is dispositioned to rework.",
            "escalate": "This case is escalated to a human reviewer.",
        }.get(decision["decision"], "Decision recorded.")
        reason = " ".join(decision.get("reasons", [])[:2])
        rule = decision.get("rule_id", "")
        cited = ", ".join(f"[{i}]" for i in ids[:6]) or "[no evidence]"
        text = f"{head} {reason} Applied rule {rule}. Evidence reviewed: {cited}."
        self._track(json.dumps(decision), text)
        return text


class OpenAIProvider(BaseProvider):
    name = "openai"

    def __init__(self) -> None:
        super().__init__()
        from openai import OpenAI  # imported lazily

        self.client = OpenAI()
        self.model = SETTINGS.openai_model

    def _json_call(self, system: str, user: str) -> dict[str, Any]:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = response.choices[0].message.content or "{}"
        self._track(system + user, content)
        return json.loads(content)

    def classify_case(self, question: str) -> dict[str, Any]:
        system = (
            "You extract structured intake fields from a manufacturing quality claim. "
            "Return JSON with keys: category (product_defect|supplier_issue|policy_question), "
            "work_order_id, defect_code (one of CORROSION, SURFACE, DIM_OUT, CRACK, LEAK, DELAM, "
            "THREAD, ELECTRICAL, or null), quantity, reasoning. Never invent an id that is not in the text."
        )
        return self._json_call(system, question)

    def choose_tool(self, state: dict[str, Any]) -> dict[str, Any]:
        system = (
            "You are choosing the next tool for a quality investigation. Available tools: "
            "search_docs{query,k}, query_orders{work_order_id}, defect_history{part_number,limit}, "
            "spc_metrics{work_order_id}, warranty_rules{part_number,defect_code}, finish{reason}. "
            "Do not repeat a call already made. Return JSON {tool, args}."
        )
        return self._json_call(system, json.dumps(state, default=str))

    def write_justification(self, decision: dict[str, Any], evidence: list[dict]) -> str:
        system = (
            "Write a short, factual justification for a quality decision. Every factual claim must "
            "reference an evidence id in square brackets, e.g. [POL-WAR-01#Corrosion defects]. "
            "Use only the ids provided. Plain text, under 120 words."
        )
        user = json.dumps({"decision": decision, "evidence": evidence}, default=str)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0,
        )
        content = response.choices[0].message.content or ""
        self._track(system + user, content)
        return content.strip()


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def __init__(self) -> None:
        super().__init__()
        import anthropic

        self.client = anthropic.Anthropic()
        self.model = SETTINGS.anthropic_model

    def _json_call(self, system: str, user: str) -> dict[str, Any]:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=700,
            temperature=0,
            system=system + " Respond with JSON only.",
            messages=[{"role": "user", "content": user}],
        )
        content = "".join(block.text for block in response.content if hasattr(block, "text"))
        self._track(system + user, content)
        start, end = content.find("{"), content.rfind("}")
        return json.loads(content[start : end + 1] if start >= 0 else "{}")

    def classify_case(self, question: str) -> dict[str, Any]:
        system = (
            "Extract structured intake fields from a manufacturing quality claim: "
            "category (product_defect|supplier_issue|policy_question), work_order_id, defect_code "
            "(CORROSION|SURFACE|DIM_OUT|CRACK|LEAK|DELAM|THREAD|ELECTRICAL|null), quantity, reasoning."
        )
        return self._json_call(system, question)

    def choose_tool(self, state: dict[str, Any]) -> dict[str, Any]:
        system = (
            "Choose the next tool call. Tools: search_docs{query,k}, query_orders{work_order_id}, "
            "defect_history{part_number,limit}, spc_metrics{work_order_id}, warranty_rules{part_number,"
            "defect_code}, finish{reason}. Return {tool, args}. Do not repeat previous calls."
        )
        return self._json_call(system, json.dumps(state, default=str))

    def write_justification(self, decision: dict[str, Any], evidence: list[dict]) -> str:
        system = (
            "Write under 120 words justifying a quality decision. Cite evidence ids in square brackets "
            "and use only the ids provided."
        )
        response = self.client.messages.create(
            model=self.model,
            max_tokens=400,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": json.dumps({"decision": decision, "evidence": evidence}, default=str)}],
        )
        content = "".join(block.text for block in response.content if hasattr(block, "text"))
        self._track(str(decision), content)
        return content.strip()


def get_provider(preference: str | None = None) -> BaseProvider:
    """Build a provider, falling back to the mock if the real one is unavailable."""
    choice = (preference or SETTINGS.provider or "mock").lower()
    if choice == "openai":
        try:
            return OpenAIProvider()
        except Exception as exc:  # pragma: no cover - depends on environment
            print(f"[warn] OpenAI provider unavailable ({exc}); falling back to mock.")
            return MockProvider()
    if choice == "anthropic":
        try:
            return AnthropicProvider()
        except Exception as exc:  # pragma: no cover
            print(f"[warn] Anthropic provider unavailable ({exc}); falling back to mock.")
            return MockProvider()
    return MockProvider()
