from datetime import UTC, datetime
from uuid import uuid4

import httpx

from app.auth.dependencies import get_authentication_service
from app.auth.principal import Principal
from app.auth.security import IssuedTokenPair
from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app


class FakeAuthenticationService:
    def __init__(self, principal: Principal) -> None:
        self.principal = principal
        self.logout_called = False

    async def login(self, tenant_id, username: str, password: str) -> IssuedTokenPair:
        if password != "correct-password":
            raise AppError(code="invalid_credentials", message="用户名或密码错误。", status_code=401)
        return IssuedTokenPair("access-token", "refresh-token", 1800)

    async def refresh(self, refresh_token: str) -> IssuedTokenPair:
        if refresh_token != "refresh-token":
            raise AppError(code="invalid_token", message="访问令牌无效或已过期。", status_code=401)
        return IssuedTokenPair("access-token-2", "refresh-token-2", 1800)

    async def authenticate_access_token(self, access_token: str) -> Principal:
        if access_token != "access-token":
            raise AppError(code="invalid_token", message="访问令牌无效或已过期。", status_code=401)
        return self.principal

    async def logout(self, access_token: str, refresh_token: str) -> None:
        assert access_token == "access-token"
        assert refresh_token == "refresh-token"
        self.logout_called = True


def make_app():
    principal = Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        username="admin",
        email="admin@example.com",
        roles=frozenset({"admin"}),
    )
    service = FakeAuthenticationService(principal)
    app = create_app(
        settings=Settings(_env_file=None, app_env="test", log_level="WARNING"),
        readiness_probes=(),
    )
    app.dependency_overrides[get_authentication_service] = lambda: service
    return app, service, principal


async def api_request(method: str, path: str, **kwargs) -> httpx.Response:
    app, _, _ = make_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


async def test_login_refresh_me_and_logout_routes() -> None:
    app, service, principal = make_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/login",
            json={
                "tenant_id": str(principal.tenant_id),
                "username": "admin",
                "password": "correct-password",
            },
        )
        me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer access-token"},
        )
        refresh = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "refresh-token"},
        )
        logout = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": "Bearer access-token"},
            json={"refresh_token": "refresh-token"},
        )

    assert login.status_code == 200
    assert login.json()["token_type"] == "bearer"
    assert login.json()["expires_in"] == 1800
    assert login.headers["cache-control"] == "no-store"
    assert login.headers["pragma"] == "no-cache"
    assert me.status_code == 200
    assert me.json()["id"] == str(principal.user_id)
    assert me.json()["roles"] == ["admin"]
    assert refresh.status_code == 200
    assert refresh.json()["access_token"] == "access-token-2"
    assert refresh.headers["cache-control"] == "no-store"
    assert refresh.headers["pragma"] == "no-cache"
    assert logout.status_code == 204
    assert logout.content == b""
    assert service.logout_called is True


async def test_protected_route_requires_bearer_token() -> None:
    response = await api_request("GET", "/api/v1/auth/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "not_authenticated"


async def test_auth_request_validation_does_not_echo_password() -> None:
    response = await api_request(
        "POST",
        "/api/v1/auth/login",
        json={
            "tenant_id": str(uuid4()),
            "username": "admin",
            "password": "pw-7x",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "pw-7x" not in response.text
