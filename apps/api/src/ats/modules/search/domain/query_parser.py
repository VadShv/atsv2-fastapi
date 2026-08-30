"""Булев парсер поисковых запросов (JUGO-171).

Парсит запросы с булевой логикой:
- AND, OR, NOT (ключевые слова, регистронезависимые)
- "закавыченные фразы" (фразовый поиск)
- (скобки для группировки)
- Неявный AND между соседними терминами (при наличии операторов)

Для plain-запросов (без операторов) используется OR-семантика:
«Python FastAPI» → python | fastapi (максимальный recall, БЫСТРЕЙШИЙ ПОИСК).
При наличии хотя бы одного оператора — полная булева логика.

Преобразует в:
- AST (для in-memory движка — булева фильтрация + извлечение терминов)
- PostgreSQL tsquery-строку (для pgvector движка — to_tsquery)

WHITEBOX AI: ошибки парсинга возвращают человекочитаемую подсказку.
БЫСТРЕЙШИЙ ПОИСК: tsquery с правильными операторами (& | ! <->).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

# ---------------------------------------------------------------------------
# Ошибки
# ---------------------------------------------------------------------------


class QueryParseError(Exception):
    """Ошибка парсинга поискового запроса.

    Содержит message (что не так) и hint (как исправить) для пользователя.
    """

    def __init__(self, message: str, hint: str = "", position: int = 0) -> None:
        self.message = message
        self.hint = hint
        self.position = position
        full = f"{message}" if not hint else f"{message} — {hint}"
        super().__init__(full)


# ---------------------------------------------------------------------------
# AST-узлы
# ---------------------------------------------------------------------------


@dataclass
class TermNode:
    """Одиночный термин."""

    word: str


@dataclass
class PhraseNode:
    """Фраза из нескольких слов (поиск подряд идущих токенов)."""

    words: list[str] = field(default_factory=list)


@dataclass
class AndNode:
    """Конъюнкция: все children должны совпасть."""

    children: list = field(default_factory=list)


@dataclass
class OrNode:
    """Дизъюнкция: хотя бы один child должен совпасть."""

    children: list = field(default_factory=list)


@dataclass
class NotNode:
    """Отрицание: child не должен совпасть."""

    child: object = None


# ---------------------------------------------------------------------------
# Токенизатор
# ---------------------------------------------------------------------------


class TokenType(StrEnum):
    TERM = "term"
    PHRASE = "phrase"
    AND = "and"
    OR = "or"
    NOT = "not"
    LPAREN = "lparen"
    RPAREN = "rparen"


@dataclass
class Token:
    type: TokenType
    value: str = ""
    position: int = 0


_WORD_CHAR = re.compile(r"\w", re.UNICODE)
_KEYWORDS = {"AND": TokenType.AND, "OR": TokenType.OR, "NOT": TokenType.NOT}


def tokenize(query: str) -> list[Token]:
    """Разбить запрос на токены.

    Токены: TERM, PHRASE, AND, OR, NOT, LPAREN, RPAREN.
    Не-словесные символы (кроме кавычек и скобок) игнорируются.
    """
    tokens: list[Token] = []
    i = 0
    n = len(query)

    while i < n:
        c = query[i]

        if c.isspace():
            i += 1
            continue

        if c == "(":
            tokens.append(Token(TokenType.LPAREN, position=i))
            i += 1
            continue

        if c == ")":
            tokens.append(Token(TokenType.RPAREN, position=i))
            i += 1
            continue

        if c == '"':
            j = i + 1
            while j < n and query[j] != '"':
                j += 1
            if j >= n:
                raise QueryParseError(
                    "Незакрытые кавычки",
                    "добавьте закрывающую кавычку",
                    position=i,
                )
            phrase = query[i + 1 : j].strip()
            if not phrase:
                raise QueryParseError(
                    "Пустые кавычки",
                    "укажите слово внутри кавычек, например python developer",
                    position=i,
                )
            tokens.append(Token(TokenType.PHRASE, value=phrase, position=i))
            i = j + 1
            continue

        if _WORD_CHAR.match(c):
            j = i
            while j < n and _WORD_CHAR.match(query[j]):
                j += 1
            word = query[i:j]
            upper = word.upper()
            if upper in _KEYWORDS:
                tokens.append(Token(_KEYWORDS[upper], position=i))
            else:
                tokens.append(Token(TokenType.TERM, value=word, position=i))
            i = j
            continue

        # Прочие символы — пропускаем
        i += 1

    return tokens


# ---------------------------------------------------------------------------
# Парсер (рекурсивный спуск)
# ---------------------------------------------------------------------------

# Грамматика:
#   or_expr   := and_expr (OR and_expr)*
#   and_expr  := not_expr ((AND)? not_expr)*
#   not_expr  := NOT not_expr | primary
#   primary   := TERM | PHRASE | LPAREN or_expr RPAREN


class _Parser:
    """Рекурсивно-нисходящий парсер булевых запросов."""

    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    def parse(self) -> object | None:
        if not self._tokens:
            return None
        node = self._or_expr()
        if self._pos < len(self._tokens):
            tok = self._tokens[self._pos]
            raise QueryParseError(
                f"Неожиданный токен {tok.value or tok.type.value}",
                "проверьте синтаксис: операторы AND/OR/NOT должны быть между терминами",
                position=tok.position,
            )
        return node

    def _peek(self) -> Token | None:
        if self._pos < len(self._tokens):
            return self._tokens[self._pos]
        return None

    def _advance(self) -> Token:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _or_expr(self) -> object:
        left = self._and_expr()
        children: list = [left]
        while True:
            tok = self._peek()
            if tok is None or tok.type != TokenType.OR:
                break
            self._advance()
            children.append(self._and_expr())
        if len(children) == 1:
            return children[0]
        return OrNode(children=children)

    def _and_expr(self) -> object:
        left = self._not_expr()
        children: list = [left]
        while True:
            tok = self._peek()
            if tok is None:
                break
            # Неявный AND: TERM, PHRASE, NOT, LPAREN продолжают конъюнкцию
            if tok.type in (
                TokenType.AND,
                TokenType.TERM,
                TokenType.PHRASE,
                TokenType.NOT,
                TokenType.LPAREN,
            ):
                if tok.type == TokenType.AND:
                    self._advance()
                children.append(self._not_expr())
            else:
                break
        if len(children) == 1:
            return children[0]
        return AndNode(children=children)

    def _not_expr(self) -> object:
        tok = self._peek()
        if tok is not None and tok.type == TokenType.NOT:
            self._advance()
            child = self._not_expr()
            return NotNode(child=child)
        return self._primary()

    def _primary(self) -> object:
        tok = self._peek()
        if tok is None:
            raise QueryParseError(
                "Неожиданный конец запроса",
                "ожидался термин, фраза или открывающая скобка",
            )
        if tok.type == TokenType.LPAREN:
            self._advance()
            node = self._or_expr()
            close = self._peek()
            if close is None or close.type != TokenType.RPAREN:
                raise QueryParseError(
                    "Несбалансированные скобки",
                    "добавьте закрывающую скобку",
                    position=tok.position,
                )
            self._advance()
            return node
        if tok.type == TokenType.TERM:
            self._advance()
            return TermNode(word=tok.value)
        if tok.type == TokenType.PHRASE:
            self._advance()
            words = tok.value.split()
            return PhraseNode(words=words)
        # AND/OR/NOT/RPAREN в недопустимой позиции
        raise QueryParseError(
            f"Неожиданный оператор {tok.value or tok.type.value}",
            "проверьте порядок: операторы должны быть между терминами или группами",
            position=tok.position,
        )


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------


def has_boolean_syntax(query: str) -> bool:
    """Проверить, содержит ли запрос явные булевы операторы или группировку.

    Возвращает True если запрос использует AND, OR, NOT, кавычки или скобки.
    Когда False — запрос является plain-списком терминов (OR-семантика для recall).
    """
    if any(c in query for c in ('"', "(", ")")):
        return True
    padded = f" {query.upper()} "
    return any(kw in padded for kw in (" AND ", " OR ", " NOT "))


def parse_query(query: str) -> object | None:
    """Распарсить булев поисковый запрос в AST.

    Возвращает None для пустого запроса.
    Бросает QueryParseError при синтаксической ошибке (с подсказкой).

    Для plain-запросов (без операторов) строит OrNode из всех терминов —
    OR-семантика даёт максимальный recall (БЫСТРЕЙШИЙ ПОИСК).
    """
    tokens = tokenize(query)
    if not tokens:
        return None

    # Plain-запрос без операторов → OR-семантика для максимального recall
    if not has_boolean_syntax(query):
        terms: list = []
        for tok in tokens:
            if tok.type == TokenType.TERM:
                terms.append(TermNode(word=tok.value))
            elif tok.type == TokenType.PHRASE:
                terms.append(PhraseNode(words=tok.value.split()))
        if not terms:
            return None
        if len(terms) == 1:
            return terms[0]
        return OrNode(children=terms)

    return _Parser(tokens).parse()


def parse_to_tsquery(query: str) -> tuple[object | None, str]:
    """Распарсить запрос и вернуть (AST, tsquery-строка).

    Бросает QueryParseError при синтаксической ошибке.
    """
    ast = parse_query(query)
    return ast, to_tsquery_string(ast)


# ---------------------------------------------------------------------------
# tsquery-конвертация
# ---------------------------------------------------------------------------

_TERM_SANITIZE = re.compile(r"[\w]+", re.UNICODE)


def _sanitize_term(word: str) -> str:
    """Очистить термин: оставить только буквенно-цифровые символы."""
    match = _TERM_SANITIZE.search(word)
    return match.group(0) if match else ""


def to_tsquery_string(node: object | None) -> str:
    """Преобразовать AST в PostgreSQL tsquery-строку.

    Операторы: & (AND), | (OR), ! (NOT), <-> (phrase).
    Скобки добавляются для сохранения приоритета.
    """
    if node is None:
        return ""
    if isinstance(node, TermNode):
        return _sanitize_term(node.word)
    if isinstance(node, PhraseNode):
        words = [_sanitize_term(w) for w in node.words]
        words = [w for w in words if w]
        if not words:
            return ""
        if len(words) == 1:
            return words[0]
        return " <-> ".join(words)
    if isinstance(node, AndNode):
        parts = [_tsquery_child(c) for c in node.children]
        parts = [p for p in parts if p]
        if not parts:
            return ""
        if len(parts) == 1:
            return parts[0]
        return " & ".join(parts)
    if isinstance(node, OrNode):
        parts = [_tsquery_child(c) for c in node.children]
        parts = [p for p in parts if p]
        if not parts:
            return ""
        if len(parts) == 1:
            return parts[0]
        return " | ".join(parts)
    if isinstance(node, NotNode):
        inner = _tsquery_child(node.child)
        if not inner:
            return ""
        return f"!{inner}"
    return ""


def _tsquery_child(node: object) -> str:
    """Конвертировать дочерний узел, добавляя скобки для составных выражений."""
    if isinstance(node, (AndNode, OrNode)):
        s = to_tsquery_string(node)
        return f"({s})" if s else ""
    return to_tsquery_string(node)


# ---------------------------------------------------------------------------
# In-memory оценка (для InMemorySearchEngine)
# ---------------------------------------------------------------------------


def evaluate(node: object | None, doc_tokens: list[str], doc_token_set: set[str]) -> bool:
    """Оценить булев AST против токенов документа.

    doc_tokens: список токенов документа (в порядке следования).
    doc_token_set: множество токенов для O(1) проверки терминов.
    """
    if node is None:
        return True
    if isinstance(node, TermNode):
        return _sanitize_term(node.word).lower() in doc_token_set
    if isinstance(node, PhraseNode):
        words = [_sanitize_term(w).lower() for w in node.words]
        words = [w for w in words if w]
        if not words:
            return True
        return _has_phrase(doc_tokens, words)
    if isinstance(node, AndNode):
        return all(evaluate(c, doc_tokens, doc_token_set) for c in node.children)
    if isinstance(node, OrNode):
        return any(evaluate(c, doc_tokens, doc_token_set) for c in node.children)
    if isinstance(node, NotNode):
        return not evaluate(node.child, doc_tokens, doc_token_set)
    return False


def _has_phrase(tokens: list[str], words: list[str]) -> bool:
    """Проверить, встречаются ли words подряд в tokens."""
    if not words:
        return True
    if len(tokens) < len(words):
        return False
    target = len(words)
    return any(tokens[i : i + target] == words for i in range(len(tokens) - target + 1))


def extract_terms(node: object | None) -> list[str]:
    """Извлечь все позитивные термины из AST для BM25-скоринга.

    Термин под NOT не включается (он не должен повышать релевантность).
    """
    if node is None:
        return []
    if isinstance(node, TermNode):
        t = _sanitize_term(node.word).lower()
        return [t] if t else []
    if isinstance(node, PhraseNode):
        return [_sanitize_term(w).lower() for w in node.words if _sanitize_term(w)]
    if isinstance(node, (AndNode, OrNode)):
        terms: list[str] = []
        for c in node.children:
            terms.extend(extract_terms(c))
        return terms
    if isinstance(node, NotNode):
        return []
    return []


# ---------------------------------------------------------------------------
# Расширение синонимами (JUGO-172)
# ---------------------------------------------------------------------------


def expand_synonyms(node: object | None, synonym_map: dict[str, list[str]]) -> object | None:
    """Расширить термины в AST синонимами.

    synonym_map: {term_lower: [synonym1, synonym2, ...]}

    TermNode("python") при наличии синонимов ["py", "python3"] превращается в:
    OrNode([TermNode("python"), TermNode("py"), TermNode("python3")])

    Фразы не расширяются (точное совпадение).
    """
    if node is None:
        return None
    if isinstance(node, TermNode):
        term = node.word.lower()
        syns = synonym_map.get(term)
        if not syns:
            return node
        children: list = [node]
        for s in syns:
            if s.strip():
                children.append(TermNode(word=s.strip()))
        return OrNode(children=children) if len(children) > 1 else node
    if isinstance(node, PhraseNode):
        return node
    if isinstance(node, AndNode):
        return AndNode(children=[expand_synonyms(c, synonym_map) for c in node.children])
    if isinstance(node, OrNode):
        return OrNode(children=[expand_synonyms(c, synonym_map) for c in node.children])
    if isinstance(node, NotNode):
        return NotNode(child=expand_synonyms(node.child, synonym_map))
    return node
