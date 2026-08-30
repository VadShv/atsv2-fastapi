"""API-слой оргструктуры (JUGO-200).

Endpoints:
    GET    /org/legal-entities                  — список юрлиц
    POST   /org/legal-entities                  — создать юрлицо
    GET    /org/legal-entities/{id}             — детали юрлица
    PATCH  /org/legal-entities/{id}             — обновить юрлицо
    DELETE /org/legal-entities/{id}             — архивировать юрлицо
    GET    /org/legal-entities/{id}/units       — корневые подразделения юрлица
    GET    /org/units/{id}                      — детали подразделения
    POST   /org/units                           — создать подразделение
    PATCH  /org/units/{id}                      — обновить подразделение
    DELETE /org/units/{id}                      — архивировать подразделение
    GET    /org/units/{id}/children             — дочерние подразделения
    GET    /org/units/{id}/subtree              — поддерево (узел + потомки)
    POST   /org/units/{id}/move                 — переместить подразделение
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from ats.infra.container_helpers import get_container
from ats.infra.middleware.problem_details import ProblemException
from ats.modules.organization.domain import LegalEntityType
from ats.shared.ids import TenantId
from ats.shared.result import is_error

router = APIRouter(prefix="/org", tags=["organization"])

_DEFAULT_TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# Pydantic-схемы: LegalEntity
# ---------------------------------------------------------------------------


class CreateLegalEntityRequest(BaseModel):
    name: str = Field(description="Название юридического лица")
    type: str = Field(default="other", description="Тип: ooo, oao, zao, ip, inc, llc, other")
    inn: str = Field(default="", description="ИНН")
    full_name: str = Field(default="", description="Полное наименование")


class UpdateLegalEntityRequest(BaseModel):
    name: str | None = None
    type: str | None = None
    inn: str | None = None
    full_name: str | None = None


class LegalEntityResponse(BaseModel):
    id: UUID
    name: str
    type: str
    inn: str
    full_name: str
    is_archived: bool
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Pydantic-схемы: OrgUnit
# ---------------------------------------------------------------------------


class CreateOrgUnitRequest(BaseModel):
    legal_entity_id: str = Field(description="ID юридического лица")
    name: str = Field(description="Название подразделения")
    parent_id: str | None = Field(default=None, description="ID родительского подразделения")


class UpdateOrgUnitRequest(BaseModel):
    name: str | None = None


class MoveOrgUnitRequest(BaseModel):
    new_parent_id: str | None = Field(
        default=None, description="ID нового родителя (None = корень)"
    )


class OrgUnitResponse(BaseModel):
    id: UUID
    legal_entity_id: UUID
    name: str
    parent_id: UUID | None = None
    path: str
    is_archived: bool
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Mappers
# ---------------------------------------------------------------------------


def _le_to_response(le) -> LegalEntityResponse:
    return LegalEntityResponse(
        id=le.id,
        name=le.name,
        type=le.type.value,
        inn=le.inn,
        full_name=le.full_name,
        is_archived=le.is_archived,
        created_at=le.created_at.isoformat(),
        updated_at=le.updated_at.isoformat(),
    )


def _unit_to_response(u) -> OrgUnitResponse:
    return OrgUnitResponse(
        id=u.id,
        legal_entity_id=u.legal_entity_id,
        name=u.name,
        parent_id=u.parent_id,
        path=u.path,
        is_archived=u.is_archived,
        created_at=u.created_at.isoformat(),
        updated_at=u.updated_at.isoformat(),
    )


def _to_le_type(value: str) -> LegalEntityType:
    try:
        return LegalEntityType(value)
    except ValueError:
        raise ProblemException(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Validation Error",
            detail=f"Неизвестный тип юридического лица: {value}",
        ) from None


# ---------------------------------------------------------------------------
# Endpoints: LegalEntity
# ---------------------------------------------------------------------------


@router.get("/legal-entities", response_model=list[LegalEntityResponse])
async def list_legal_entities(include_archived: bool = False) -> list[LegalEntityResponse]:
    container = get_container()
    entities = await container.legal_entity_use_case.list_all(_DEFAULT_TENANT, include_archived)
    return [_le_to_response(e) for e in entities]


@router.post(
    "/legal-entities",
    response_model=LegalEntityResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_legal_entity(req: CreateLegalEntityRequest) -> LegalEntityResponse:
    container = get_container()
    result = await container.legal_entity_use_case.create(
        _DEFAULT_TENANT,
        name=req.name,
        type=_to_le_type(req.type),
        inn=req.inn,
        full_name=req.full_name,
    )
    if is_error(result):
        raise ProblemException(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Validation Error",
            detail=result.error.message,
        )
    return _le_to_response(result.value)


@router.get("/legal-entities/{legal_entity_id}", response_model=LegalEntityResponse)
async def get_legal_entity(legal_entity_id: str) -> LegalEntityResponse:
    container = get_container()
    result = await container.legal_entity_use_case.get(_DEFAULT_TENANT, legal_entity_id)
    if is_error(result):
        raise ProblemException(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Not Found",
            detail=result.error.message,
        )
    return _le_to_response(result.value)


@router.patch("/legal-entities/{legal_entity_id}", response_model=LegalEntityResponse)
async def update_legal_entity(
    legal_entity_id: str, req: UpdateLegalEntityRequest
) -> LegalEntityResponse:
    container = get_container()
    le_type = _to_le_type(req.type) if req.type is not None else None
    result = await container.legal_entity_use_case.update(
        _DEFAULT_TENANT,
        legal_entity_id,
        name=req.name,
        type=le_type,
        inn=req.inn,
        full_name=req.full_name,
    )
    if is_error(result):
        code = result.error.code
        status_code = (
            status.HTTP_404_NOT_FOUND if code.value == "not_found" else status.HTTP_400_BAD_REQUEST
        )
        raise ProblemException(
            status_code=status_code,
            title="Error",
            detail=result.error.message,
        )
    return _le_to_response(result.value)


@router.delete("/legal-entities/{legal_entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_legal_entity(legal_entity_id: str) -> None:
    container = get_container()
    result = await container.legal_entity_use_case.archive(_DEFAULT_TENANT, legal_entity_id)
    if is_error(result):
        raise ProblemException(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Not Found",
            detail=result.error.message,
        )


@router.get(
    "/legal-entities/{legal_entity_id}/units",
    response_model=list[OrgUnitResponse],
)
async def list_root_units(
    legal_entity_id: str, include_archived: bool = False
) -> list[OrgUnitResponse]:
    container = get_container()
    units = await container.org_unit_use_case.list_root_units(
        _DEFAULT_TENANT, legal_entity_id, include_archived
    )
    return [_unit_to_response(u) for u in units]


# ---------------------------------------------------------------------------
# Endpoints: OrgUnit
# ---------------------------------------------------------------------------


@router.post("/units", response_model=OrgUnitResponse, status_code=status.HTTP_201_CREATED)
async def create_org_unit(req: CreateOrgUnitRequest) -> OrgUnitResponse:
    container = get_container()
    result = await container.org_unit_use_case.create(
        _DEFAULT_TENANT,
        legal_entity_id=req.legal_entity_id,
        name=req.name,
        parent_id=req.parent_id,
    )
    if is_error(result):
        code = result.error.code
        status_code = (
            status.HTTP_404_NOT_FOUND if code.value == "not_found" else status.HTTP_400_BAD_REQUEST
        )
        raise ProblemException(
            status_code=status_code,
            title="Error",
            detail=result.error.message,
        )
    return _unit_to_response(result.value)


@router.get("/units/{org_unit_id}", response_model=OrgUnitResponse)
async def get_org_unit(org_unit_id: str) -> OrgUnitResponse:
    container = get_container()
    result = await container.org_unit_use_case.get(_DEFAULT_TENANT, org_unit_id)
    if is_error(result):
        raise ProblemException(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Not Found",
            detail=result.error.message,
        )
    return _unit_to_response(result.value)


@router.patch("/units/{org_unit_id}", response_model=OrgUnitResponse)
async def update_org_unit(org_unit_id: str, req: UpdateOrgUnitRequest) -> OrgUnitResponse:
    container = get_container()
    result = await container.org_unit_use_case.update(_DEFAULT_TENANT, org_unit_id, name=req.name)
    if is_error(result):
        code = result.error.code
        status_code = (
            status.HTTP_404_NOT_FOUND if code.value == "not_found" else status.HTTP_400_BAD_REQUEST
        )
        raise ProblemException(
            status_code=status_code,
            title="Error",
            detail=result.error.message,
        )
    return _unit_to_response(result.value)


@router.delete("/units/{org_unit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_org_unit(org_unit_id: str) -> None:
    container = get_container()
    result = await container.org_unit_use_case.archive(_DEFAULT_TENANT, org_unit_id)
    if is_error(result):
        code = result.error.code
        status_code = (
            status.HTTP_404_NOT_FOUND if code.value == "not_found" else status.HTTP_400_BAD_REQUEST
        )
        raise ProblemException(
            status_code=status_code,
            title="Error",
            detail=result.error.message,
        )


@router.get("/units/{org_unit_id}/children", response_model=list[OrgUnitResponse])
async def list_children(org_unit_id: str, include_archived: bool = False) -> list[OrgUnitResponse]:
    container = get_container()
    units = await container.org_unit_use_case.list_children(
        _DEFAULT_TENANT, org_unit_id, include_archived
    )
    return [_unit_to_response(u) for u in units]


@router.get("/units/{org_unit_id}/subtree", response_model=list[OrgUnitResponse])
async def get_subtree(org_unit_id: str, include_archived: bool = False) -> list[OrgUnitResponse]:
    container = get_container()
    result = await container.org_unit_use_case.get_subtree(
        _DEFAULT_TENANT, org_unit_id, include_archived
    )
    if is_error(result):
        raise ProblemException(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Not Found",
            detail=result.error.message,
        )
    return [_unit_to_response(u) for u in result.value]


@router.post("/units/{org_unit_id}/move", response_model=OrgUnitResponse)
async def move_org_unit(org_unit_id: str, req: MoveOrgUnitRequest) -> OrgUnitResponse:
    container = get_container()
    result = await container.org_unit_use_case.move(_DEFAULT_TENANT, org_unit_id, req.new_parent_id)
    if is_error(result):
        code = result.error.code
        if code.value == "not_found":
            status_code = status.HTTP_404_NOT_FOUND
        elif code.value == "conflict":
            status_code = status.HTTP_409_CONFLICT
        else:
            status_code = status.HTTP_400_BAD_REQUEST
        raise ProblemException(
            status_code=status_code,
            title="Error",
            detail=result.error.message,
        )
    return _unit_to_response(result.value)
