"""In-memory поисковый движок для dev/тестов (ATS_STUB_MODE).

БЫСТРЕЙШИЙ ПОИСК: гибридный BM25 ⊕ vector ⊕ фильтры → re-rank + фасеты.
Реализует тот же SearchEngine-порт, что и pgvector-адаптер, но хранит в памяти.
Используется в dev-режиме и в тестах без Postgres.

JUGO-171: булев парсер запросов (AND/OR/NOT/фразы/скобки) — фильтрация + BM25.
          Plain-запросы (без операторов) не фильтруют жёстко — только скорят
          по BM25 для максимального recall + семантического векторного поиска.
JUGO-172: расширение запроса синонимами перед парсингом.
"""

from __future__ import annotations

import math
import re
import time
from collections import Counter
from typing import Any
from uuid import UUID

from ats.modules.search.domain.models import (
    Facet,
    FacetValue,
    SearchableDocument,
    SearchFilter,
    SearchHit,
    SearchQuery,
    SearchResult,
)
from ats.modules.search.domain.query_parser import (
    QueryParseError,
    evaluate,
    expand_synonyms,
    extract_terms,
    has_boolean_syntax,
    parse_query,
)
from ats.modules.search.ports.search_engine import SearchEngine

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


class InMemorySearchEngine(SearchEngine):
    """In-memory гибридный поисковый движок.

    BM25 — по токенам searchable_text; vector — косинусное сходство эмбеддингов.
    Финальный score = w_bm25 * bm25 + w_vec * cosine. Фасеты считаются по metadata.
    """

    def __init__(self) -> None:
        self._docs: dict[tuple[UUID, UUID], SearchableDocument] = {}

    async def index(self, document: SearchableDocument) -> None:
        key = (document.tenant_id, document.id)
        self._docs[key] = document

    async def remove(self, tenant_id, document_id) -> None:  # type: ignore[no-untyped-def]
        self._docs.pop((tenant_id, document_id), None)

    async def search(self, query: SearchQuery) -> SearchResult:
        start = time.monotonic()
        tenant_docs = [d for d in self._docs.values() if d.tenant_id == query.tenant_id]

        if not tenant_docs:
            return SearchResult(hits=[], total=0, query=query.query)

        # JUGO-171: булев парсер запросов
        ast, is_boolean = self._parse_query(query)
        q_tokens = extract_terms(ast) if ast else _tokenize(query.query)

        q_vec = query.query_embedding

        # --- Фильтрация по metadata ---
        filtered = [d for d in tenant_docs if _matches_filters(d, query.filters)]

        # JUGO-171: жёсткая булева фильтрация только для запросов с операторами.
        # Plain-запросы не фильтруют — только скорят (recall + vector semantic).
        if is_boolean and ast is not None:
            filtered = [d for d in filtered if self._matches_bool(d, ast)]

        if not filtered:
            return SearchResult(hits=[], total=0, query=query.query)

        # --- BM25 ---
        bm25_scores = self._bm25(filtered, q_tokens)

        # --- Vector (cosine) ---
        vec_scores: dict[UUID, float] = {}
        if q_vec:
            for doc in filtered:
                if doc.embedding:
                    vec_scores[doc.id] = _cosine(q_vec, doc.embedding)

        # --- Гибридный re-rank ---
        bm25_w = query.bm25_weight if q_vec else 1.0
        vec_w = query.vector_weight if q_vec else 0.0
        total_w = bm25_w + vec_w
        if total_w > 0:
            bm25_w /= total_w
            vec_w /= total_w

        scored: list[SearchHit] = []
        for doc in filtered:
            b = bm25_scores.get(doc.id, 0.0)
            v = vec_scores.get(doc.id, 0.0)
            score = bm25_w * b + vec_w * v
            scored.append(
                SearchHit(
                    document_id=doc.id,
                    score=score,
                    bm25_score=b,
                    vector_score=v,
                    metadata=doc.metadata,
                    snippet=_snippet(doc.text, q_tokens),
                )
            )

        scored.sort(key=lambda h: h.score, reverse=True)
        total = len(scored)
        page = scored[query.offset : query.offset + query.limit]

        # --- Фасеты ---
        facets = _compute_facets(tenant_docs, query.facet_fields)

        took_ms = int((time.monotonic() - start) * 1000)
        return SearchResult(
            hits=page,
            total=total,
            facets=facets,
            took_ms=took_ms,
            query=query.query,
        )

    def _parse_query(self, query: SearchQuery) -> tuple[object | None, bool]:
        """Распарсить булев запрос с расширением синонимами.

        Возвращает (AST, is_boolean):
        - AST: дерево запроса или None (пустой/нераспарсенный запрос).
        - is_boolean: True если запрос содержит булевы операторы (жёсткая фильтрация).

        При ошибке парсинга логирует и возвращает (None, False) (fallback на plain).
        """
        try:
            ast = parse_query(query.query)
        except QueryParseError:
            # Fallback: plain tokenization без булевой логики
            return None, False

        if ast is None:
            return None, False

        # JUGO-172: расширение синонимами
        if query.synonym_map:
            ast = expand_synonyms(ast, query.synonym_map)

        is_bool = has_boolean_syntax(query.query)
        return ast, is_bool

    def _matches_bool(self, doc: SearchableDocument, ast) -> bool:
        """Проверить соответствие документа булевому AST."""
        tokens = _tokenize(doc.text)
        token_set = set(tokens)
        return evaluate(ast, tokens, token_set)

    def _bm25(self, docs: list[SearchableDocument], q_tokens: list[str]) -> dict[UUID, float]:
        """BM25 по Okapi. Классическая формула ранжирования."""
        if not q_tokens:
            return {d.id: 0.0 for d in docs}

        n = len(docs)
        avgdl = sum(len(_tokenize(d.text)) for d in docs) / n if n else 0.0

        df: Counter[str] = Counter()
        doc_tokens: dict[UUID, list[str]] = {}
        doc_len: dict[UUID, int] = {}
        for doc in docs:
            toks = _tokenize(doc.text)
            doc_tokens[doc.id] = toks
            doc_len[doc.id] = len(toks)
            for term in set(toks):
                df[term] += 1

        k1 = 1.5
        b = 0.75
        scores: dict[UUID, float] = {}
        for doc in docs:
            toks = doc_tokens[doc.id]
            tf: Counter[str] = Counter(toks)
            dl = doc_len[doc.id]
            score = 0.0
            for term in q_tokens:
                if term not in tf:
                    continue
                idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                tf_val = tf[term]
                denom = tf_val + k1 * (1 - b + b * dl / avgdl) if avgdl else tf_val
                score += idf * (tf_val * (k1 + 1)) / denom
            scores[doc.id] = score
        return scores


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _matches_filters(doc: SearchableDocument, filters: list[SearchFilter]) -> bool:
    for f in filters:
        field_val = doc.metadata.get(f.field)
        if not _match_one(field_val, f):
            return False
    return True


def _match_one(field_val: Any, f: SearchFilter) -> bool:
    if field_val is None:
        return False
    if f.operator in ("any", "all"):
        values = [str(v) for v in field_val] if isinstance(field_val, list) else [str(field_val)]
        if f.operator == "any":
            return any(v in values for v in f.values)
        return all(v in values for v in f.values)
    if f.operator == "gte":
        try:
            return float(field_val) >= float(f.values[0])
        except (TypeError, ValueError, IndexError):
            return False
    if f.operator == "lte":
        try:
            return float(field_val) <= float(f.values[0])
        except (TypeError, ValueError, IndexError):
            return False
    return False


def _snippet(text: str, q_tokens: list[str], max_len: int = 160) -> str:
    if not text:
        return ""
    if not q_tokens:
        return text[:max_len]
    lower = text.lower()
    pos = len(text)
    for term in q_tokens:
        idx = lower.find(term)
        if idx != -1 and idx < pos:
            pos = idx
    start = max(0, pos - 30)
    snippet = text[start : start + max_len]
    prefix = "…" if start > 0 else ""
    suffix = "…" if start + max_len < len(text) else ""
    return prefix + snippet + suffix


def _compute_facets(docs: list[SearchableDocument], fields: list[str]) -> list[Facet]:
    result: list[Facet] = []
    for field in fields:
        counter: Counter[str] = Counter()
        for doc in docs:
            val = doc.metadata.get(field)
            if val is None:
                continue
            if isinstance(val, list):
                for v in val:
                    counter[str(v)] += 1
            else:
                counter[str(val)] += 1
        result.append(
            Facet(
                field=field,
                values=[FacetValue(value=v, count=c) for v, c in counter.most_common()],
            )
        )
    return result
