from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.auth.dependencies import (
    AccessSession,
    get_access_session,
    get_authentication_service,
    get_current_principal,
)
from app.auth.principal import Principal
from app.auth.schemas import (
    CurrentUserResponse,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    TokenPairResponse,
)
from app.auth.security import IssuedTokenPair
from app.auth.service import AuthenticationService

router = APIRouter(prefix="/auth", tags=["auth"])
AuthServiceDependency = Annotated[
    AuthenticationService,
    Depends(get_authentication_service),
]
CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
CurrentAccessSession = Annotated[AccessSession, Depends(get_access_session)]


def token_response(pair: IssuedTokenPair) -> TokenPairResponse:
    return TokenPairResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.access_expires_in,
    )


@router.post("/login", response_model=TokenPairResponse, summary="用户登录")
async def login(
    request: LoginRequest,
    response: Response,
    service: AuthServiceDependency,
) -> TokenPairResponse:
    pair = await service.login(
        request.tenant_id,
        request.username,
        request.password.get_secret_value(),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return token_response(pair)


@router.post("/refresh", response_model=TokenPairResponse, summary="刷新令牌")
async def refresh(
    request: RefreshRequest,
    response: Response,
    service: AuthServiceDependency,
) -> TokenPairResponse:
    pair = await service.refresh(request.refresh_token.get_secret_value())
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return token_response(pair)


@router.get("/me", response_model=CurrentUserResponse, summary="当前用户")
async def me(principal: CurrentPrincipal) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=principal.user_id,
        tenant_id=principal.tenant_id,
        username=principal.username,
        email=principal.email,
        roles=sorted(principal.roles),
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="退出并吊销令牌",
)
async def logout(
    request: LogoutRequest,
    access_session: CurrentAccessSession,
    service: AuthServiceDependency,
) -> Response:
    await service.logout(
        access_session.access_token,
        request.refresh_token.get_secret_value(),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
