"""Тесты JUGO-170..172: search_vector aggregate, булев парсер, синонимы.

JUGO-170: build_search_text() — агрегация ФИО+заголовок+компании+навыки+резюме.
JUGO-171: булев парсер (AND/OR/NOT, кавычки, скобки) → tsquery + ошибки с подсказками.
JUGO-172: словарь синонимов — расширение запроса + CRUD API.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from ats.infra.container_helpers import get_container, reset_container
from ats.infra.search.in_memory_search_engine import InMemorySearchEngine
from ats.main import app
from ats.modules.search.domain.models import (
    SearchableDocument,
    SearchQuery,
)
from ats.modules.search.domain.query_parser import (
    AndNode,
    NotNode,
    OrNode,
    PhraseNode,
    QueryParseError,
    TermNode,
    TokenType,
    evaluate,
    expand_synonyms,
    extract_terms,
    has_boolean_syntax,
    parse_query,
    parse_to_tsquery,
    to_tsquery_string,
)
from ats.modules.search.domain.synonym import SynonymEntry
from ats.shared.ids import TenantId

TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_container()


# ===========================================================================
# JUGO-170: build_search_text
# ===========================================================================


class TestBuildSearchText:
    """Тесты агрегации поискового текста кандидата."""

    def test_aggregates_all_fields(self) -> None:
        from ats.modules.search.domain.models import build_search_text

        result = build_search_text(
            full_name="Иван Иванов",
            headline="Python Developer",
            skills=["Python", "FastAPI"],
            companies=["Yandex", "Google"],
            resume_text="Опыт работы 5 лет",
        )
        assert "Иван" in result
        assert "Python" in result
        assert "FastAPI" in result
        assert "Yandex" in result
        assert "Google" in result
        assert "Опыт" in result

    def test_deduplicates_duplicates(self) -> None:
        from ats.modules.search.domain.models import build_search_text

        result = build_search_text(
            full_name="Python Developer",
            headline="python developer",
            skills=["Python Developer"],
            companies=["python developer"],
            resume_text="Python Developer",
        )
        # Полная строка-дубликат удалена — встречается один раз
        assert result.lower().count("python developer") == 1

    def test_handles_empty_fields(self) -> None:
        from ats.modules.search.domain.models import build_search_text

        result = build_search_text(full_name="Иван", headline="", skills=None, companies=None)
        assert result.strip() == "Иван"

    def test_empty_all_returns_empty(self) -> None:
        from ats.modules.search.domain.models import build_search_text

        result = build_search_text(full_name="", headline="", skills=[], companies=[])
        assert result == ""

    def test_order_significant_fields_first(self) -> None:
        from ats.modules.search.domain.models import build_search_text

        result = build_search_text(
            full_name="Иван",
            headline="Developer",
            skills=["Python"],
            companies=["Yandex"],
            resume_text="Experience text",
        )
        # ФИО идёт первым, текст резюме — последним
        assert result.index("Иван") < result.index("Experience")


# ===========================================================================
# JUGO-171: Булев парсер
# ===========================================================================


class TestBooleanTokenizer:
    """Тесты токенизатора."""

    def test_simple_terms(self) -> None:
        from ats.modules.search.domain.query_parser import tokenize

        tokens = tokenize("python developer")
        assert len(tokens) == 2
        assert tokens[0].value == "python"
        assert tokens[1].value == "developer"

    def test_keywords_case_insensitive(self) -> None:
        from ats.modules.search.domain.query_parser import tokenize

        tokens = tokenize("python AND developer")
        assert len(tokens) == 3
        assert tokens[1].type == TokenType.AND

    def test_lowercase_and(self) -> None:
        from ats.modules.search.domain.query_parser import tokenize

        tokens = tokenize("python and developer")
        assert len(tokens) == 3
        assert tokens[1].type == TokenType.AND

    def test_phrase_in_quotes(self) -> None:
        from ats.modules.search.domain.query_parser import tokenize

        tokens = tokenize('"python developer" java')
        assert len(tokens) == 2
        assert tokens[0].value == "python developer"

    def test_parentheses(self) -> None:
        from ats.modules.search.domain.query_parser import tokenize

        tokens = tokenize("(python OR java) AND senior")
        # LPAREN, python, OR, java, RPAREN, AND, senior
        assert len(tokens) == 7
        assert tokens[0].type == TokenType.LPAREN
        assert tokens[4].type == TokenType.RPAREN

    def test_russian_terms(self) -> None:
        from ats.modules.search.domain.query_parser import tokenize

        tokens = tokenize("разработчик AND питон")
        assert len(tokens) == 3
        assert tokens[0].value == "разработчик"

    def test_unclosed_quote_raises_error(self) -> None:
        from ats.modules.search.domain.query_parser import tokenize

        with pytest.raises(QueryParseError) as exc_info:
            tokenize('"python developer')
        assert "кавычк" in exc_info.value.message.lower()

    def test_empty_quotes_raise_error(self) -> None:
        from ats.modules.search.domain.query_parser import tokenize

        with pytest.raises(QueryParseError) as exc_info:
            tokenize('""')
        assert "пуст" in exc_info.value.message.lower()


class TestBooleanParser:
    """Тесты парсера булевых запросов."""

    def test_single_term(self) -> None:
        ast = parse_query("python")
        assert isinstance(ast, TermNode)
        assert ast.word == "python"

    def test_plain_query_becomes_or(self) -> None:
        ast = parse_query("python developer")
        assert isinstance(ast, OrNode)
        assert len(ast.children) == 2

    def test_explicit_and(self) -> None:
        ast = parse_query("python AND developer")
        assert isinstance(ast, AndNode)
        assert len(ast.children) == 2

    def test_explicit_or(self) -> None:
        ast = parse_query("python OR developer")
        assert isinstance(ast, OrNode)
        assert len(ast.children) == 2

    def test_not(self) -> None:
        ast = parse_query("python NOT java")
        assert isinstance(ast, AndNode)
        assert isinstance(ast.children[1], NotNode)

    def test_leading_not(self) -> None:
        ast = parse_query("NOT java")
        assert isinstance(ast, NotNode)

    def test_phrase(self) -> None:
        ast = parse_query('"python developer"')
        assert isinstance(ast, PhraseNode)
        assert ast.words == ["python", "developer"]

    def test_parentheses_grouping(self) -> None:
        ast = parse_query("(python OR java) AND senior")
        assert isinstance(ast, AndNode)
        assert isinstance(ast.children[0], OrNode)

    def test_complex_query(self) -> None:
        ast = parse_query("(python OR java) AND senior NOT junior")
        assert ast is not None

    def test_empty_query_returns_none(self) -> None:
        ast = parse_query("")
        assert ast is None

    def test_whitespace_only_returns_none(self) -> None:
        ast = parse_query("   ")
        assert ast is None

    def test_unbalanced_parens_raises_error(self) -> None:
        with pytest.raises(QueryParseError) as exc_info:
            parse_query("(python AND java")
        assert "скобк" in exc_info.value.message.lower()
        assert exc_info.value.hint  # Есть подсказка

    def test_trailing_and_raises_error(self) -> None:
        with pytest.raises(QueryParseError) as exc_info:
            parse_query("python AND")
        assert exc_info.value.hint  # Есть подсказка

    def test_error_has_position(self) -> None:
        with pytest.raises(QueryParseError) as exc_info:
            parse_query('"unclosed')
        assert exc_info.value.position >= 0


class TestHasBooleanSyntax:
    """Тесты определения булева синтаксиса."""

    def test_plain_query_no_syntax(self) -> None:
        assert not has_boolean_syntax("python developer")

    def test_and_keyword(self) -> None:
        assert has_boolean_syntax("python AND developer")

    def test_or_keyword(self) -> None:
        assert has_boolean_syntax("python OR developer")

    def test_not_keyword(self) -> None:
        assert has_boolean_syntax("python NOT developer")

    def test_quotes(self) -> None:
        assert has_boolean_syntax('"python developer"')

    def test_parentheses(self) -> None:
        assert has_boolean_syntax("(python)")

    def test_lowercase_and(self) -> None:
        assert has_boolean_syntax("python and developer")

    def test_word_containing_and(self) -> None:
        # "Android" содержит "and" но это часть слова
        assert not has_boolean_syntax("Android developer")

    def test_leading_not(self) -> None:
        assert has_boolean_syntax("NOT java")


class TestTsqueryConversion:
    """Тесты конвертации AST → tsquery-строка."""

    def test_term(self) -> None:
        ast = parse_query("python")
        assert to_tsquery_string(ast) == "python"

    def test_and(self) -> None:
        ast = parse_query("python AND developer")
        assert to_tsquery_string(ast) == "python & developer"

    def test_or(self) -> None:
        ast = parse_query("python OR developer")
        assert to_tsquery_string(ast) == "python | developer"

    def test_not(self) -> None:
        ast = parse_query("NOT java")
        assert to_tsquery_string(ast) == "!java"

    def test_phrase(self) -> None:
        ast = parse_query('"python developer"')
        assert to_tsquery_string(ast) == "python <-> developer"

    def test_grouped(self) -> None:
        ast = parse_query("(python OR java) AND senior")
        result = to_tsquery_string(ast)
        assert "|" in result
        assert "&" in result
        assert "(" in result
        assert ")" in result

    def test_plain_query_or(self) -> None:
        ast = parse_query("python developer")
        assert to_tsquery_string(ast) == "python | developer"

    def test_none_returns_empty(self) -> None:
        assert to_tsquery_string(None) == ""

    def test_parse_to_tsquery_combined(self) -> None:
        ast, tsq = parse_to_tsquery("python AND java")
        assert tsq == "python & java"
        assert isinstance(ast, AndNode)

    def test_sanitizes_special_chars(self) -> None:
        ast = parse_query("python!@#")
        result = to_tsquery_string(ast)
        assert "!" not in result
        assert "@" not in result


class TestEvaluate:
    """Тесты in-memory оценки булева AST."""

    def _doc_tokens(self, text: str) -> tuple[list[str], set[str]]:
        import re

        tokens = [t.lower() for t in re.findall(r"\w+", text, re.UNICODE)]
        return tokens, set(tokens)

    def test_term_match(self) -> None:
        ast = parse_query("python")
        tokens, token_set = self._doc_tokens("python developer")
        assert evaluate(ast, tokens, token_set) is True

    def test_term_no_match(self) -> None:
        ast = parse_query("rust")
        tokens, token_set = self._doc_tokens("python developer")
        assert evaluate(ast, tokens, token_set) is False

    def test_and_match(self) -> None:
        ast = parse_query("python AND developer")
        tokens, token_set = self._doc_tokens("python developer senior")
        assert evaluate(ast, tokens, token_set) is True

    def test_and_no_match(self) -> None:
        ast = parse_query("python AND rust")
        tokens, token_set = self._doc_tokens("python developer")
        assert evaluate(ast, tokens, token_set) is False

    def test_or_match(self) -> None:
        ast = parse_query("python OR rust")
        tokens, token_set = self._doc_tokens("rust developer")
        assert evaluate(ast, tokens, token_set) is True

    def test_not_excludes(self) -> None:
        ast = parse_query("python NOT java")
        tokens, token_set = self._doc_tokens("python developer")
        assert evaluate(ast, tokens, token_set) is True

    def test_not_excludes_when_present(self) -> None:
        ast = parse_query("python NOT java")
        tokens, token_set = self._doc_tokens("python java developer")
        assert evaluate(ast, tokens, token_set) is False

    def test_phrase_match(self) -> None:
        ast = parse_query('"python developer"')
        tokens, token_set = self._doc_tokens("senior python developer here")
        assert evaluate(ast, tokens, token_set) is True

    def test_phrase_no_match_wrong_order(self) -> None:
        ast = parse_query('"python developer"')
        tokens, token_set = self._doc_tokens("developer python here")
        assert evaluate(ast, tokens, token_set) is False

    def test_none_returns_true(self) -> None:
        tokens, token_set = self._doc_tokens("python")
        assert evaluate(None, tokens, token_set) is True


class TestExtractTerms:
    """Тесты извлечения терминов для BM25."""

    def test_single_term(self) -> None:
        ast = parse_query("python")
        assert extract_terms(ast) == ["python"]

    def test_and_terms(self) -> None:
        ast = parse_query("python AND developer")
        terms = extract_terms(ast)
        assert "python" in terms
        assert "developer" in terms

    def test_not_terms_excluded(self) -> None:
        ast = parse_query("python NOT java")
        terms = extract_terms(ast)
        assert "python" in terms
        assert "java" not in terms

    def test_phrase_terms(self) -> None:
        ast = parse_query('"python developer"')
        terms = extract_terms(ast)
        assert "python" in terms
        assert "developer" in terms

    def test_none_returns_empty(self) -> None:
        assert extract_terms(None) == []


class TestExpandSynonyms:
    """Тесты расширения запроса синонимами."""

    def test_expands_term(self) -> None:
        ast = parse_query("python")
        expanded = expand_synonyms(ast, {"python": ["py", "python3"]})
        assert isinstance(expanded, OrNode)
        assert len(expanded.children) == 3

    def test_no_synonyms_unchanged(self) -> None:
        ast = parse_query("python")
        expanded = expand_synonyms(ast, {})
        assert expanded is ast

    def test_phrase_not_expanded(self) -> None:
        ast = parse_query('"python developer"')
        expanded = expand_synonyms(ast, {"python": ["py"]})
        assert expanded is ast

    def test_and_with_synonyms(self) -> None:
        ast = parse_query("python AND senior")
        expanded = expand_synonyms(ast, {"python": ["py"]})
        assert isinstance(expanded, AndNode)
        assert isinstance(expanded.children[0], OrNode)

    def test_not_with_synonyms(self) -> None:
        ast = parse_query("python NOT java")
        expanded = expand_synonyms(ast, {"java": ["jvm"]})
        assert isinstance(expanded, AndNode)
        not_node = expanded.children[1]
        assert isinstance(not_node, NotNode)
        assert isinstance(not_node.child, OrNode)


# ===========================================================================
# JUGO-170/171: In-memory движок с булевыми запросами
# ===========================================================================


def _doc(doc_id: str, text: str, skills: list[str] | None = None) -> SearchableDocument:
    return SearchableDocument(
        id=uuid.UUID(doc_id),
        tenant_id=TENANT.value,
        text=text,
        metadata={"skills": skills or []},
    )


class TestInMemoryBooleanSearch:
    """Тесты булева поиска через InMemorySearchEngine."""

    @pytest.mark.asyncio
    async def test_and_filter(self) -> None:
        engine = InMemorySearchEngine()
        await engine.index(_doc("11111111-0000-0000-0000-000000000001", "python developer"))
        await engine.index(_doc("22222222-0000-0000-0000-000000000002", "python manager"))

        result = await engine.search(
            SearchQuery(tenant_id=TENANT.value, query="python AND developer", limit=10)
        )
        assert result.total == 1
        assert result.hits[0].document_id == uuid.UUID("11111111-0000-0000-0000-000000000001")

    @pytest.mark.asyncio
    async def test_or_filter(self) -> None:
        engine = InMemorySearchEngine()
        await engine.index(_doc("11111111-0000-0000-0000-000000000001", "python developer"))
        await engine.index(_doc("22222222-0000-0000-0000-000000000002", "rust developer"))

        result = await engine.search(
            SearchQuery(tenant_id=TENANT.value, query="python OR rust", limit=10)
        )
        assert result.total == 2

    @pytest.mark.asyncio
    async def test_not_filter(self) -> None:
        engine = InMemorySearchEngine()
        await engine.index(_doc("11111111-0000-0000-0000-000000000001", "python developer"))
        await engine.index(_doc("22222222-0000-0000-0000-000000000002", "python java"))

        result = await engine.search(
            SearchQuery(tenant_id=TENANT.value, query="python NOT java", limit=10)
        )
        assert result.total == 1
        assert result.hits[0].document_id == uuid.UUID("11111111-0000-0000-0000-000000000001")

    @pytest.mark.asyncio
    async def test_phrase_search(self) -> None:
        engine = InMemorySearchEngine()
        await engine.index(_doc("11111111-0000-0000-0000-000000000001", "senior python developer"))
        await engine.index(_doc("22222222-0000-0000-0000-000000000002", "developer python senior"))

        result = await engine.search(
            SearchQuery(tenant_id=TENANT.value, query='"python developer"', limit=10)
        )
        assert result.total == 1
        assert result.hits[0].document_id == uuid.UUID("11111111-0000-0000-0000-000000000001")

    @pytest.mark.asyncio
    async def test_parentheses_grouping(self) -> None:
        engine = InMemorySearchEngine()
        await engine.index(_doc("11111111-0000-0000-0000-000000000001", "python senior"))
        await engine.index(_doc("22222222-0000-0000-0000-000000000002", "java senior"))
        await engine.index(_doc("33333333-0000-0000-0000-000000000003", "rust junior"))

        result = await engine.search(
            SearchQuery(tenant_id=TENANT.value, query="(python OR java) AND senior", limit=10)
        )
        assert result.total == 2

    @pytest.mark.asyncio
    async def test_plain_query_no_hard_filter(self) -> None:
        """Plain-запрос (без операторов) не фильтрует жёстко — только скорит."""
        engine = InMemorySearchEngine()
        await engine.index(_doc("11111111-0000-0000-0000-000000000001", "python developer"))
        await engine.index(_doc("22222222-0000-0000-0000-000000000002", "java developer"))

        result = await engine.search(SearchQuery(tenant_id=TENANT.value, query="python", limit=10))
        # Оба документа возвращаются (plain-семантика), но python-документ скорит выше
        assert result.total == 2
        assert result.hits[0].bm25_score >= result.hits[1].bm25_score

    @pytest.mark.asyncio
    async def test_synonym_expansion_in_search(self) -> None:
        """Синонимы расширяют plain-запрос для максимального recall."""
        engine = InMemorySearchEngine()
        await engine.index(_doc("11111111-0000-0000-0000-000000000001", "python developer"))
        await engine.index(_doc("22222222-0000-0000-0000-000000000002", "py developer"))

        result = await engine.search(
            SearchQuery(
                tenant_id=TENANT.value,
                query="python",
                limit=10,
                synonym_map={"python": ["py"]},
            )
        )
        # Оба документа найдены благодаря расширению синонимом
        assert result.total == 2

    @pytest.mark.asyncio
    async def test_boolean_with_synonym_expansion(self) -> None:
        """Булев запрос расширяется синонимами."""
        engine = InMemorySearchEngine()
        await engine.index(_doc("11111111-0000-0000-0000-000000000001", "python developer"))
        await engine.index(_doc("22222222-0000-0000-0000-000000000002", "py developer"))
        await engine.index(_doc("33333333-0000-0000-0000-000000000003", "rust developer"))

        result = await engine.search(
            SearchQuery(
                tenant_id=TENANT.value,
                query="python AND developer",
                limit=10,
                synonym_map={"python": ["py"]},
            )
        )
        # python AND developer → расширяется до (python|py) AND developer
        assert result.total == 2


# ===========================================================================
# JUGO-172: Синонимы — домен + репозиторий + API
# ===========================================================================


class TestSynonymEntry:
    """Тесты доменной модели синонимов."""

    def test_create_entry(self) -> None:
        entry = SynonymEntry(
            tenant_id=TENANT.value,
            term="python",
            synonyms=["py", "python3"],
        )
        assert entry.term == "python"
        assert entry.synonyms == ["py", "python3"]

    def test_normalizes_term(self) -> None:
        entry = SynonymEntry(
            tenant_id=TENANT.value,
            term="  Python  ",
            synonyms=["py"],
        )
        assert entry.term == "Python"

    def test_deduplicates_synonyms(self) -> None:
        entry = SynonymEntry(
            tenant_id=TENANT.value,
            term="python",
            synonyms=["py", "Py", "PY", "python3"],
        )
        assert entry.synonyms == ["py", "python3"]

    def test_strips_empty_synonyms(self) -> None:
        entry = SynonymEntry(
            tenant_id=TENANT.value,
            term="python",
            synonyms=["py", "", "  ", "python3"],
        )
        assert entry.synonyms == ["py", "python3"]

    def test_empty_term_raises(self) -> None:
        with pytest.raises(ValueError):
            SynonymEntry(tenant_id=TENANT.value, term="", synonyms=[])

    def test_to_map_entry(self) -> None:
        entry = SynonymEntry(
            tenant_id=TENANT.value,
            term="Python",
            synonyms=["Py", "Python3"],
        )
        term, syns = entry.to_map_entry()
        assert term == "python"
        assert syns == ["py", "python3"]


class TestInMemorySynonymRepository:
    """Тесты in-memory репозитория синонимов."""

    @pytest.mark.asyncio
    async def test_save_and_list(self) -> None:
        from ats.infra.stubs_search import InMemorySynonymRepository

        repo = InMemorySynonymRepository()
        entry = SynonymEntry(tenant_id=TENANT.value, term="python", synonyms=["py"])
        await repo.save(entry)

        all_entries = await repo.list_all(TENANT)
        assert len(all_entries) == 1
        assert all_entries[0].term == "python"

    @pytest.mark.asyncio
    async def test_find_by_term(self) -> None:
        from ats.infra.stubs_search import InMemorySynonymRepository

        repo = InMemorySynonymRepository()
        entry = SynonymEntry(tenant_id=TENANT.value, term="python", synonyms=["py"])
        await repo.save(entry)

        found = await repo.find_by_term(TENANT, "Python")
        assert found is not None
        assert found.term == "python"

    @pytest.mark.asyncio
    async def test_upsert_by_term(self) -> None:
        from ats.infra.stubs_search import InMemorySynonymRepository

        repo = InMemorySynonymRepository()
        entry1 = SynonymEntry(tenant_id=TENANT.value, term="python", synonyms=["py"])
        await repo.save(entry1)

        entry2 = SynonymEntry(tenant_id=TENANT.value, term="python", synonyms=["python3"])
        await repo.save(entry2)

        all_entries = await repo.list_all(TENANT)
        assert len(all_entries) == 1
        assert all_entries[0].synonyms == ["python3"]

    @pytest.mark.asyncio
    async def test_delete(self) -> None:
        from ats.infra.stubs_search import InMemorySynonymRepository

        repo = InMemorySynonymRepository()
        entry = SynonymEntry(tenant_id=TENANT.value, term="python", synonyms=["py"])
        saved = await repo.save(entry)

        deleted = await repo.delete(TENANT, str(saved.id))
        assert deleted is True

        all_entries = await repo.list_all(TENANT)
        assert len(all_entries) == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self) -> None:
        from ats.infra.stubs_search import InMemorySynonymRepository

        repo = InMemorySynonymRepository()
        deleted = await repo.delete(TENANT, str(uuid.uuid4()))
        assert deleted is False

    @pytest.mark.asyncio
    async def test_get_synonym_map(self) -> None:
        from ats.infra.stubs_search import InMemorySynonymRepository

        repo = InMemorySynonymRepository()
        await repo.save(
            SynonymEntry(tenant_id=TENANT.value, term="python", synonyms=["py", "python3"])
        )
        await repo.save(SynonymEntry(tenant_id=TENANT.value, term="java", synonyms=["jvm"]))

        synonym_map = await repo.get_synonym_map(TENANT)
        assert synonym_map["python"] == ["py", "python3"]
        assert synonym_map["java"] == ["jvm"]

    @pytest.mark.asyncio
    async def test_tenant_isolation(self) -> None:
        from ats.infra.stubs_search import InMemorySynonymRepository

        repo = InMemorySynonymRepository()
        tenant2 = TenantId.from_string("00000000-0000-0000-0000-000000000002")
        await repo.save(SynonymEntry(tenant_id=TENANT.value, term="python", synonyms=["py"]))
        await repo.save(SynonymEntry(tenant_id=tenant2.value, term="java", synonyms=["jvm"]))

        tenant1_entries = await repo.list_all(TENANT)
        tenant2_entries = await repo.list_all(tenant2)
        assert len(tenant1_entries) == 1
        assert len(tenant2_entries) == 1
        assert tenant1_entries[0].term == "python"
        assert tenant2_entries[0].term == "java"


class TestSynonymAPI:
    """Тесты CRUD API синонимов."""

    @pytest.mark.asyncio
    async def test_create_synonym(self) -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/search/synonyms",
                json={"term": "python", "synonyms": ["py", "python3"]},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["term"] == "python"
        assert "py" in data["synonyms"]

    @pytest.mark.asyncio
    async def test_list_synonyms(self) -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            await ac.post(
                "/api/v1/search/synonyms",
                json={"term": "python", "synonyms": ["py"]},
            )
            await ac.post(
                "/api/v1/search/synonyms",
                json={"term": "java", "synonyms": ["jvm"]},
            )
            resp = await ac.get("/api/v1/search/synonyms")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    @pytest.mark.asyncio
    async def test_get_synonym_by_id(self) -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            create_resp = await ac.post(
                "/api/v1/search/synonyms",
                json={"term": "python", "synonyms": ["py"]},
            )
            entry_id = create_resp.json()["id"]
            resp = await ac.get(f"/api/v1/search/synonyms/{entry_id}")
        assert resp.status_code == 200
        assert resp.json()["term"] == "python"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_404(self) -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/v1/search/synonyms/{uuid.uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_synonym(self) -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            create_resp = await ac.post(
                "/api/v1/search/synonyms",
                json={"term": "python", "synonyms": ["py"]},
            )
            entry_id = create_resp.json()["id"]
            resp = await ac.delete(f"/api/v1/search/synonyms/{entry_id}")
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_404(self) -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.delete(f"/api/v1/search/synonyms/{uuid.uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_upsert_synonym(self) -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            await ac.post(
                "/api/v1/search/synonyms",
                json={"term": "python", "synonyms": ["py"]},
            )
            await ac.post(
                "/api/v1/search/synonyms",
                json={"term": "python", "synonyms": ["python3"]},
            )
            list_resp = await ac.get("/api/v1/search/synonyms")
        data = list_resp.json()
        assert len(data) == 1
        assert data[0]["synonyms"] == ["python3"]


class TestSearchWithSynonymsViaAPI:
    """Сквозной тест: создание синонимов → поиск с расширением."""

    @pytest.mark.asyncio
    async def test_synonym_expansion_in_search(self) -> None:
        container = get_container()
        await container.search_engine.index(
            _doc("11111111-0000-0000-0000-000000000001", "python developer")
        )
        await container.search_engine.index(
            _doc("22222222-0000-0000-0000-000000000002", "py developer")
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # Создаём синоним
            await ac.post(
                "/api/v1/search/synonyms",
                json={"term": "python", "synonyms": ["py"]},
            )
            # Ищем "python" — должны найти оба (python + py)
            resp = await ac.post(
                "/api/v1/search/candidates",
                json={"query": "python", "skip_embedding": True},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2


class TestSearchQuerySyntaxErrorsViaAPI:
    """Тесты обработки синтаксических ошибок через API (JUGO-171)."""

    @pytest.mark.asyncio
    async def test_unclosed_quote_returns_400_with_hint(self) -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/search/candidates",
                json={"query": '"python developer', "skip_embedding": True},
            )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "кавычк" in detail.lower()

    @pytest.mark.asyncio
    async def test_unbalanced_parens_returns_400_with_hint(self) -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/search/candidates",
                json={"query": "(python AND java", "skip_embedding": True},
            )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "скобк" in detail.lower()

    @pytest.mark.asyncio
    async def test_empty_quotes_returns_400(self) -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/search/candidates",
                json={"query": '""', "skip_embedding": True},
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_trailing_and_returns_400(self) -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/search/candidates",
                json={"query": "python AND", "skip_embedding": True},
            )
        assert resp.status_code == 400
