from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.dependencies import require_any_role
from app.auth.principal import Principal
from app.users.dependencies import get_user_service
from app.users.schemas import UserCreateRequest, UserResponse, UserUpdateRequest
from app.users.service import UserService

router = APIRouter(prefix="/users", tags=["users"])
AdminPrincipal = Annotated[Principal, Depends(require_any_role("admin"))]
UserServiceDependency = Annotated[UserService, Depends(get_user_service)]


@router.get("", response_model=list[UserResponse], summary="查询租户用户")
async def list_users(
    principal: AdminPrincipal,
    service: UserServiceDependency,
) -> list[UserResponse]:
    return await service.list_users(principal)


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建租户用户",
)
async def create_user(
    request: UserCreateRequest,
    principal: AdminPrincipal,
    service: UserServiceDependency,
) -> UserResponse:
    return await service.create_user(principal, request)


@router.patch("/{user_id}", response_model=UserResponse, summary="修改租户用户")
async def update_user(
    user_id: UUID,
    request: UserUpdateRequest,
    principal: AdminPrincipal,
    service: UserServiceDependency,
) -> UserResponse:
    return await service.update_user(principal, user_id, request)
