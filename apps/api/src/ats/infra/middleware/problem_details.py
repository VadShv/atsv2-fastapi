"""RFC 9457 Problem Details for HTTP APIs (application/problem+json).

Контракт ТЗ §14.3:
    {"type", "title", "status", "detail", "errors": [{field, code, message}], "trace_id"}

SECURE FIRST: trace_id в каждом ответе — позволяет связать ошибку с логом/трейсом.
WHITEBOX AI: детальная структура errors[] с field/code/message — прозрачная диагностика.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ats.infra.logging.context import get_log_context
from ats.infra.tracing.context import get_current_trace_id

logger = logging.getLogger(__name__)


class ProblemErrorDetail(BaseModel):
    """Ошибка конкретного поля (валидация, бизнес-правило)."""

    field: str = Field(description="Имя поля или путь (напр. 'email', 'items[0].name')")
    code: str = Field(description="Машинный код ошибки (напр. 'invalid_format')")
    message: str = Field(description="Человекочитаемое сообщение")


class ProblemDetail(BaseModel):
    """RFC 9457 Problem Details.

    Сериализуется как application/problem+json.
    """

    type: str = Field(default="about:blank", description="URI-ссылка на тип ошибки")
    title: str = Field(description="Краткий заголовок ошибки")
    status: int = Field(description="HTTP status code")
    detail: str = Field(default="", description="Детальное описание")
    errors: list[ProblemErrorDetail] = Field(
        default_factory=list,
        description="Ошибки полей (валидация)",
    )
    trace_id: str = Field(default="", description="Идентификатор трассировки для логов")


def _resolve_trace_id() -> str:
    """Получить trace_id из OTel span или contextvars."""
    trace_id = get_current_trace_id()
    if trace_id:
        return trace_id
    return get_log_context("trace_id") or ""


class ProblemException(Exception):
    """Доменное исключение для problem+json ответов.

    Бросается в use cases / API-слое, перехватывается глобальным handler.
    """

    def __init__(
        self,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        title: str = "Bad Request",
        detail: str = "",
        type_: str = "about:blank",
        errors: list[ProblemErrorDetail] | None = None,
    ) -> None:
        self.status_code = status_code
        self.title = title
        self.detail = detail
        self.type_ = type_
        self.errors = errors or []
        super().__init__(detail or title)


async def problem_exception_handler(request: Request, exc: ProblemException) -> JSONResponse:
    """Обработчик ProblemException -> application/problem+json."""
    trace_id = _resolve_trace_id()
    problem = ProblemDetail(
        type=exc.type_,
        title=exc.title,
        status=exc.status_code,
        detail=exc.detail,
        errors=exc.errors,
        trace_id=trace_id,
    )
    return _build_response(problem)


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Обработчик FastAPI HTTPException -> problem+json (обратная совместимость)."""
    trace_id = _resolve_trace_id()
    detail = str(exc.detail) if not isinstance(exc.detail, dict) else ""
    errors: list[ProblemErrorDetail] = []
    if isinstance(exc.detail, dict) and "errors" in exc.detail:
        errors = [
            ProblemErrorDetail(**e)
            if isinstance(e, dict)
            else ProblemErrorDetail(field="", code="", message=str(e))
            for e in exc.detail["errors"]
        ]
        detail = exc.detail.get("detail", "")

    problem = ProblemDetail(
        title=_http_title(exc.status_code),
        status=exc.status_code,
        detail=detail,
        errors=errors,
        trace_id=trace_id,
    )
    return _build_response(problem)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Обработчик Pydantic validation errors -> problem+json с errors[]."""
    trace_id = _resolve_trace_id()
    errors: list[ProblemErrorDetail] = []
    for err in exc.errors():
        field_path = ".".join(str(loc) for loc in err.get("loc", []) if loc != "body")
        if not field_path:
            field_path = "body"
        errors.append(
            ProblemErrorDetail(
                field=field_path,
                code=err.get("type", "validation_error"),
                message=err.get("msg", "Invalid value"),
            )
        )

    problem = ProblemDetail(
        title="Validation Error",
        status=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail="One or more fields failed validation",
        errors=errors,
        trace_id=trace_id,
    )
    return _build_response(problem)


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all: 500 Internal Server Error -> problem+json (без утечки деталей).

    SECURE FIRST: стек-трейс не попадает в ответ; только trace_id.
    """
    logger.exception("Unhandled exception: %s", type(exc).__name__)
    trace_id = _resolve_trace_id()
    problem = ProblemDetail(
        title="Internal Server Error",
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="An unexpected error occurred. Contact support with the trace_id.",
        trace_id=trace_id,
    )
    return _build_response(problem)


def _build_response(problem: ProblemDetail) -> JSONResponse:
    """Сериализовать ProblemDetail -> JSONResponse с правильным content-type."""
    return JSONResponse(
        status_code=problem.status,
        content=jsonable_encoder(problem),
        media_type="application/problem+json",
        headers={"X-Trace-Id": problem.trace_id} if problem.trace_id else {},
    )


def _http_title(status_code: int) -> str:
    """Человекочитаемый заголовок для HTTP status code."""
    titles = {
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        409: "Conflict",
        422: "Unprocessable Content",
        429: "Too Many Requests",
        500: "Internal Server Error",
        502: "Bad Gateway",
        503: "Service Unavailable",
        504: "Gateway Timeout",
    }
    return titles.get(status_code, "Error")


def register_problem_handlers(app: Any) -> None:
    """Зарегистрировать все problem+json handlers на FastAPI приложении.

    Вызывается в create_app() после создания app, но до middleware.
    """
    app.add_exception_handler(ProblemException, problem_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
