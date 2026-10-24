"""Hybrid retrieval over the synthetic markdown knowledge base.

Pure standard library: BM25 over tokens, blended with a TF-IDF cosine score.
No embeddings service, no network — which is the constraint that makes the demo
runnable on an air-gapped client machine.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from .config import DOCS_DIR

TOKEN_RE = re.compile(r"[a-z0-9_]+")
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "for", "on", "with",
    "as", "by", "be", "that", "this", "it", "at", "from", "we", "must", "not", "if",
}


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    section: str
    text: str
    tokens: list[str]


class KnowledgeBase:
    """Chunks documents by H2 section and searches them."""

    def __init__(self, docs_dir: Path | None = None) -> None:
        self.docs_dir = docs_dir or DOCS_DIR
        self.chunks: list[Chunk] = []
        self._df: dict[str, int] = {}
        self._avgdl = 0.0
        self._load()
        self._build_index()

    # -- loading --------------------------------------------------------
    def _load(self) -> None:
        if not self.docs_dir.exists():
            raise FileNotFoundError(
                f"Document folder {self.docs_dir} not found. Run: python scripts/seed_data.py"
            )
        for path in sorted(self.docs_dir.glob("*.md")):
            doc_id = path.stem
            raw = path.read_text(encoding="utf-8")
            sections = re.split(r"^##\s+", raw, flags=re.M)
            for block in sections[1:]:
                lines = block.strip().splitlines()
                if not lines:
                    continue
                heading = lines[0].strip()
                body = "\n".join(lines[1:]).strip()
                if not body:
                    continue
                # Keep chunks small enough for a tight context window.
                for i in range(0, len(body), 900):
                    piece = body[i : i + 900].strip()
                    if not piece:
                        continue
                    suffix = "" if i == 0 else f" (part {i // 900 + 1})"
                    text = f"{heading}: {piece}"
                    self.chunks.append(
                        Chunk(
                            chunk_id=f"{doc_id}#{heading}{suffix}",
                            doc_id=doc_id,
                            section=heading + suffix,
                            text=text,
                            tokens=tokenize(text),
                        )
                    )

    # -- index ----------------------------------------------------------
    def _build_index(self) -> None:
        self._df = {}
        for chunk in self.chunks:
            for term in set(chunk.tokens):
                self._df[term] = self._df.get(term, 0) + 1
        self._avgdl = sum(len(c.tokens) for c in self.chunks) / max(1, len(self.chunks))

    def _idf(self, term: str) -> float:
        n = len(self.chunks)
        df = self._df.get(term, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def _bm25(self, query: list[str], chunk: Chunk, k1: float = 1.5, b: float = 0.75) -> float:
        score = 0.0
        length = len(chunk.tokens) or 1
        for term in query:
            tf = chunk.tokens.count(term)
            if tf == 0:
                continue
            denom = tf + k1 * (1 - b + b * length / (self._avgdl or 1))
            score += self._idf(term) * (tf * (k1 + 1)) / denom
        return score

    def _cosine(self, query: list[str], chunk: Chunk) -> float:
        if not query or not chunk.tokens:
            return 0.0
        q_terms = set(query)
        dot = sum(self._idf(t) for t in q_terms if t in chunk.tokens)
        q_norm = math.sqrt(sum(self._idf(t) ** 2 for t in q_terms)) or 1.0
        c_norm = math.sqrt(sum(self._idf(t) ** 2 for t in set(chunk.tokens))) or 1.0
        return dot / (q_norm * c_norm)

    # -- search ---------------------------------------------------------
    def search(self, query: str, k: int = 4) -> list[dict]:
        terms = tokenize(query)
        if not terms:
            return []
        scored = []
        for chunk in self.chunks:
            score = 0.65 * self._bm25(terms, chunk) + 0.35 * self._cosine(terms, chunk) * 4.0
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        out = []
        for score, chunk in scored[:k]:
            out.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "section": chunk.section,
                    "text": chunk.text,
                    "score": round(score, 3),
                }
            )
        return out


_CACHE: KnowledgeBase | None = None


def get_kb() -> KnowledgeBase:
    global _CACHE
    if _CACHE is None:
        _CACHE = KnowledgeBase()
    return _CACHE
