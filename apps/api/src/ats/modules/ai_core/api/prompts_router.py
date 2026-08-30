"""API-слой ai_core: промпт-реестр (Prompt Registry API).

E-31: whitebox-управление промптами. Список, детали, рендер, playground.
Промпты — версионный код, поэтому API read-only (кроме playground/preview).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ats.infra.container_helpers import get_container
from ats.modules.ai_core.domain.models import AIRequest, ChatMessage, MessageRole
from ats.modules.ai_core.prompts.registry import REGISTRY, get_prompt
from ats.shared.ids import TenantId

router = APIRouter(prefix="/prompts", tags=["prompts"])

_DEFAULT_TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")

# Резолвер: имя класса-схемы → Pydantic-модель для structured output.
# Только схемы, которые поддерживаются gateway.structured().
_SCHEMA_REGISTRY: dict[str, type[BaseModel]] = {}


def _register_schema(name: str, model: type[BaseModel]) -> type[BaseModel]:
    _SCHEMA_REGISTRY[name] = model
    return model


# Ленивая регистрация схем (импорт может быть тяжёлым)
def _ensure_schemas() -> None:
    if _SCHEMA_REGISTRY:
        return
    from ats.modules.ai_core.prompts.schemas import ScreeningCriteriaOutput
    from ats.modules.candidates.domain.parsed_resume import ParsedResume

    _register_schema("ScreeningCriteriaOutput", ScreeningCriteriaOutput)
    _register_schema("ParsedResume", ParsedResume)
    from ats.modules.m1_screening.domain.scoring_output import ScreeningScoreOutput

    _register_schema("ScreeningScoreOutput", ScreeningScoreOutput)


def _resolve_schema(name: str | None) -> type[BaseModel] | None:
    if name is None:
        return None
    _ensure_schemas()
    return _SCHEMA_REGISTRY.get(name)


# ---------------------------------------------------------------------------
# Pydantic-схемы ответов
# ---------------------------------------------------------------------------


class PromptSummaryResponse(BaseModel):
    """Краткая сводка промпта (для списка)."""

    id: str
    version: str
    name: str
    description: str
    output_format: str
    output_schema: str | None = None
    model_hint: str | None = None
    temperature: float
    variables: list[str]


class PromptListResponse(BaseModel):
    """Список всех зарегистрированных промптов."""

    prompts: list[PromptSummaryResponse]
    total: int


class PromptDetailResponse(BaseModel):
    """Детали промпта: метаданные + системный промпт + шаблон."""

    id: str
    version: str
    name: str
    description: str
    system: str
    template: str = Field(description="Сырой текст шаблона с {{переменными}}")
    output_format: str
    output_schema: str | None = None
    model_hint: str | None = None
    temperature: float
    variables: list[str]


class RenderPromptRequest(BaseModel):
    """Запрос на рендер промпта переменными."""

    variables: dict[str, str] = Field(
        default_factory=dict, description="Значения переменных шаблона"
    )


class RenderPromptResponse(BaseModel):
    """Результат рендера: готовый user_message + input_hash (whitebox)."""

    system: str
    user_message: str
    input_hash: str
    variables: dict[str, str]


class PlaygroundRequest(BaseModel):
    """Запрос на запуск промпта через AIGateway (playground)."""

    variables: dict[str, str] = Field(
        default_factory=dict, description="Значения переменных шаблона"
    )
    model: str | None = Field(default=None, description="Переопределение модели")
    temperature: float | None = Field(default=None, description="Переопределение temperature")


class PlaygroundResponse(BaseModel):
    """Результат playground: raw output + parsed (если structured) + provenance."""

    prompt_id: str
    prompt_version: str
    model: str
    output_format: str
    raw_output: str
    parsed_output: Any | None = Field(
        default=None, description="Распарсенный JSON, если output_format=json"
    )
    provenance_id: str | None = None
    latency_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    repaired: bool = False


# ---------------------------------------------------------------------------
# Эндпоинты
# ---------------------------------------------------------------------------


def _get_spec_or_404(prompt_id: str, version: str):
    """Получить PromptSpec или выбросить 404."""
    try:
        return get_prompt(prompt_id, version)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Промпт не найден: {prompt_id}:v{version}",
        ) from None


@router.get(
    "",
    response_model=PromptListResponse,
    summary="Список всех зарегистрированных промптов",
)
async def list_prompts() -> PromptListResponse:
    summaries = [
        PromptSummaryResponse(
            id=spec.id,
            version=spec.version,
            name=spec.name,
            description=spec.description,
            output_format=spec.output_format.value,
            output_schema=spec.output_schema,
            model_hint=spec.model_hint,
            temperature=spec.temperature,
            variables=spec.variables,
        )
        for spec in REGISTRY.values()
    ]
    # Сортировка: по id, затем по версии (стабильный порядок)
    summaries.sort(key=lambda s: (s.id, s.version))
    return PromptListResponse(prompts=summaries, total=len(summaries))


@router.get(
    "/{prompt_id}/{version}",
    response_model=PromptDetailResponse,
    summary="Детали промпта: метаданные + системный промпт + шаблон",
)
async def get_prompt_detail(prompt_id: str, version: str) -> PromptDetailResponse:
    spec = _get_spec_or_404(prompt_id, version)
    return PromptDetailResponse(
        id=spec.id,
        version=spec.version,
        name=spec.name,
        description=spec.description,
        system=spec.system,
        template=spec.load_template(),
        output_format=spec.output_format.value,
        output_schema=spec.output_schema,
        model_hint=spec.model_hint,
        temperature=spec.temperature,
        variables=spec.variables,
    )


@router.post(
    "/{prompt_id}/{version}/render",
    response_model=RenderPromptResponse,
    summary="Рендер промпта переменными (preview без вызова LLM)",
)
async def render_prompt(
    prompt_id: str, version: str, body: RenderPromptRequest
) -> RenderPromptResponse:
    spec = _get_spec_or_404(prompt_id, version)
    user_message, input_hash = spec.render(body.variables)
    return RenderPromptResponse(
        system=spec.system,
        user_message=user_message,
        input_hash=input_hash,
        variables=body.variables,
    )


@router.post(
    "/{prompt_id}/{version}/playground",
    response_model=PlaygroundResponse,
    summary="Запуск промпта через AIGateway (playground / тестовый прогон)",
)
async def playground(prompt_id: str, version: str, body: PlaygroundRequest) -> PlaygroundResponse:
    spec = _get_spec_or_404(prompt_id, version)

    # Рендер
    user_text, input_hash = spec.render(body.variables)

    request = AIRequest(
        tenant_id=_DEFAULT_TENANT,
        prompt_id=spec.id,
        prompt_version=spec.version,
        messages=[
            ChatMessage(role=MessageRole.SYSTEM, content=spec.system),
            ChatMessage(role=MessageRole.USER, content=user_text),
        ],
        model=body.model or spec.model_hint,
        temperature=body.temperature if body.temperature is not None else spec.temperature,
        skill="playground",
        input_refs={"input_hash": input_hash},
        variables=body.variables,
    )

    container = get_container()
    gateway = container.ai_gateway

    # Если есть схема → structured, иначе — text completion
    schema = _resolve_schema(spec.output_schema)
    if schema is not None:
        response = await gateway.structured(request, schema)
        return PlaygroundResponse(
            prompt_id=spec.id,
            prompt_version=spec.version,
            model=response.model,
            output_format=spec.output_format.value,
            raw_output=response.raw_output,
            parsed_output=response.parsed.model_dump(mode="json"),
            provenance_id=str(response.provenance_id.value),
            latency_ms=response.latency_ms,
            tokens_in=response.usage.tokens_in,
            tokens_out=response.usage.tokens_out,
            cost_usd=response.usage.cost_usd,
            repaired=response.repaired,
        )

    # Text completion
    response_text = await gateway.complete(request)
    return PlaygroundResponse(
        prompt_id=spec.id,
        prompt_version=spec.version,
        model=response_text.model,
        output_format=spec.output_format.value,
        raw_output=response_text.raw_output,
        parsed_output=None,
        provenance_id=str(response_text.provenance_id.value),
        latency_ms=response_text.latency_ms,
        tokens_in=response_text.usage.tokens_in,
        tokens_out=response_text.usage.tokens_out,
        cost_usd=response_text.usage.cost_usd,
        repaired=False,
    )
