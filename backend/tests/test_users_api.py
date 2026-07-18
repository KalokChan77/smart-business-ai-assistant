from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx

from app.auth.dependencies import get_authentication_service
from app.auth.principal import Principal
from app.auth.security import IssuedTokenPair
from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from app.users.dependencies import get_user_service
from app.users.models import UserStatus
from app.users.schemas import UserResponse


class RoleAwareAuthenticationService:
    def __init__(self, principal: Principal) -> None:
        self.principal = principal

    async def authenticate_access_token(self, access_token: str) -> Principal:
        if access_token != "access-token":
            raise AppError(code="invalid_token", message="令牌无效。", status_code=401)
        return self.principal


class FakeUserService:
    def __init__(self, tenant_id: UUID) -> None:
        now = datetime.now(UTC)
        self.user = UserResponse(
            id=uuid4(),
            tenant_id=tenant_id,
            username="demo-user",
            email="demo@example.com",
            status=UserStatus.ACTIVE,
            roles=["user"],
            created_at=now,
            updated_at=now,
        )

    async def list_users(self, principal: Principal) -> list[UserResponse]:
        return [self.user]

    async def create_user(self, principal: Principal, request) -> UserResponse:
        return self.user.model_copy(
            update={
                "username": request.username.strip().lower(),
                "email": request.email.strip().lower(),
                "roles": sorted(request.role_codes),
            }
        )

    async def update_user(self, principal: Principal, user_id: UUID, request) -> UserResponse:
        assert user_id == self.user.id
        updates = {}
        if request.email is not None:
            updates["email"] = request.email
        if request.status is not None:
            updates["status"] = request.status
        if request.role_codes is not None:
            updates["roles"] = sorted(request.role_codes)
        return self.user.model_copy(update=updates)


def make_app(role: str):
    principal = Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        username="current",
        email="current@example.com",
        roles=frozenset({role}),
    )
    auth = RoleAwareAuthenticationService(principal)
    users = FakeUserService(principal.tenant_id)
    app = create_app(
        settings=Settings(_env_file=None, app_env="test", log_level="WARNING"),
        readiness_probes=(),
    )
    app.dependency_overrides[get_authentication_service] = lambda: auth
    app.dependency_overrides[get_user_service] = lambda: users
    return app, users


async def test_non_admin_cannot_access_user_management() -> None:
    app, _ = make_app("user")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/users",
            headers={"Authorization": "Bearer access-token"},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_admin_can_list_create_and_update_tenant_users() -> None:
    app, users = make_app("admin")
    headers = {"Authorization": "Bearer access-token"}
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        listed = await client.get("/api/v1/users", headers=headers)
        created = await client.post(
            "/api/v1/users",
            headers=headers,
            json={
                "username": " NewUser ",
                "email": "NEW@example.com",
                "password": "correct-password",
                "role_codes": ["user"],
            },
        )
        updated = await client.patch(
            f"/api/v1/users/{users.user.id}",
            headers=headers,
            json={"status": "disabled"},
        )

    assert listed.status_code == 200
    assert listed.json()[0]["tenant_id"] == str(users.user.tenant_id)
    assert created.status_code == 201
    assert created.json()["username"] == "newuser"
    assert updated.status_code == 200
    assert updated.json()["status"] == "disabled"

async def test_invalid_role_code_is_rejected_before_service_execution() -> None:
    app, _ = make_app("admin")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/users",
            headers={"Authorization": "Bearer access-token"},
            json={
                "username": "valid-user",
                "email": "valid@example.com",
                "password": "correct-password",
                "role_codes": ["admin!"],
            },
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"

