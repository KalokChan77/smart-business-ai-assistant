"""Run a disposable authenticated customer-service assistance smoke flow."""

import asyncio
import os
import secrets
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
from pydantic import SecretStr
from sqlalchemy import delete, func, select

from app.auth.principal import Principal
from app.auth.security import JwtTokenService, PasswordService, TokenType
from app.cache.client import create_redis_client
from app.core.asyncio_compat import run_async
from app.core.config import Settings
from app.customer_service.models import (
    CustomerTicket,
    CustomerTicketStatus,
    ReplySuggestion,
    ReplySuggestionStatus,
)
from app.db.session import Database
from app.users.models import Role, User
from app.users.repository import UsersRepository
from app.users.schemas import UserCreateRequest
from app.users.service import UserService


def require_secret(value: SecretStr | None, name: str) -> str:
    if value is None or not value.get_secret_value().strip():
        raise RuntimeError(f"{name} must be configured.")
    return value.get_secret_value().strip()


def require_status(response: httpx.Response, expected: int, stage: str) -> None:
    if response.status_code != expected:
        raise AssertionError(f"{stage} returned HTTP {response.status_code}.")


def assert_safe_response(
    response: httpx.Response,
    protected_values: tuple[str, ...],
) -> dict[str, object]:
    if any(value and value in response.text for value in protected_values):
        raise AssertionError("A protected value appeared in a customer-service response.")
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError("Customer-service response payload is not an object.")
    return payload


def require_error_code(payload: dict[str, object]) -> str:
    error = payload.get("error")
    if not isinstance(error, dict):
        raise AssertionError("Error response has no error object.")
    code = error.get("code")
    if not isinstance(code, str):
        raise AssertionError("Error response has no stable code.")
    return code


async def login(
    client: httpx.AsyncClient,
    *,
    tenant_id: UUID,
    username: str,
    password: str,
    stage: str,
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "tenant_id": str(tenant_id),
            "username": username,
            "password": password,
        },
    )
    require_status(response, 200, stage)
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError(f"{stage} payload is not an object.")
    return payload


def auth_headers(pair: dict[str, object]) -> dict[str, str]:
    return {"Authorization": f"Bearer {pair['access_token']}"}


async def fixture_counts(
    database: Database,
    tenant_ids: tuple[UUID, ...],
    ticket_id: UUID | None,
) -> tuple[int, int, int, int]:
    async with database.session_factory() as session:
        ticket_count = 0
        suggestion_count = 0
        if ticket_id is not None:
            ticket_count = int(
                (
                    await session.scalar(
                        select(func.count())
                        .select_from(CustomerTicket)
                        .where(CustomerTicket.id == ticket_id)
                    )
                )
                or 0
            )
            suggestion_count = int(
                (
                    await session.scalar(
                        select(func.count())
                        .select_from(ReplySuggestion)
                        .where(ReplySuggestion.ticket_id == ticket_id)
                    )
                )
                or 0
            )
        user_count = int(
            (
                await session.scalar(
                    select(func.count())
                    .select_from(User)
                    .where(User.tenant_id.in_(tenant_ids))
                )
            )
            or 0
        )
        role_count = int(
            (
                await session.scalar(
                    select(func.count())
                    .select_from(Role)
                    .where(Role.tenant_id.in_(tenant_ids))
                )
            )
            or 0
        )
        return ticket_count, suggestion_count, user_count, role_count


async def verify() -> None:
    settings = Settings()
    database_url = require_secret(settings.database_url, "DATABASE_URL")
    redis_url = require_secret(settings.redis_url, "REDIS_URL")
    jwt_secret = require_secret(settings.jwt_secret_key, "JWT_SECRET_KEY")
    settings_secrets = tuple(
        value.get_secret_value().strip()
        for field_name in settings.__class__.model_fields
        if isinstance((value := getattr(settings, field_name)), SecretStr)
        and value.get_secret_value().strip()
    )

    database = Database.create(database_url)
    redis = create_redis_client(redis_url)
    tokens = JwtTokenService(
        secret=jwt_secret,
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        access_ttl=timedelta(minutes=settings.jwt_access_ttl_minutes),
        refresh_ttl=timedelta(days=settings.jwt_refresh_ttl_days),
    )
    tenant_id = uuid4()
    outsider_tenant_id = uuid4()
    tenant_ids = (tenant_id, outsider_tenant_id)
    suffix = uuid4().hex[:8]
    admin_password = secrets.token_urlsafe(24)
    requester_password = secrets.token_urlsafe(24)
    peer_password = secrets.token_urlsafe(24)
    staff_password = secrets.token_urlsafe(24)
    outsider_password = secrets.token_urlsafe(24)
    issued_tokens: list[tuple[str, TokenType]] = []
    redis_keys: set[str] = set()
    ticket_id: UUID | None = None

    try:
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            admin = await users.bootstrap_admin(
                tenant_id=tenant_id,
                username=f"cs-smoke-admin-{suffix}",
                email=f"cs-smoke-admin-{suffix}@example.test",
                password=admin_password,
            )
        admin_principal = Principal(
            user_id=admin.id,
            tenant_id=tenant_id,
            username=admin.username,
            email=admin.email,
            roles=frozenset({"admin"}),
        )
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            requester = await users.create_user(
                admin_principal,
                UserCreateRequest(
                    username=f"cs-smoke-requester-{suffix}",
                    email=f"cs-smoke-requester-{suffix}@example.test",
                    password=requester_password,
                    role_codes={"user"},
                ),
            )
            peer = await users.create_user(
                admin_principal,
                UserCreateRequest(
                    username=f"cs-smoke-peer-{suffix}",
                    email=f"cs-smoke-peer-{suffix}@example.test",
                    password=peer_password,
                    role_codes={"user"},
                ),
            )
            staff = await users.create_user(
                admin_principal,
                UserCreateRequest(
                    username=f"cs-smoke-staff-{suffix}",
                    email=f"cs-smoke-staff-{suffix}@example.test",
                    password=staff_password,
                    role_codes={"customer_service"},
                ),
            )
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            outsider = await users.bootstrap_admin(
                tenant_id=outsider_tenant_id,
                username=f"cs-smoke-outsider-{suffix}",
                email=f"cs-smoke-outsider-{suffix}@example.test",
                password=outsider_password,
            )

        base_url = os.getenv(
            "CUSTOMER_SERVICE_SMOKE_BASE_URL",
            "http://127.0.0.1:8000",
        )
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=60,
            trust_env=False,
        ) as client:
            requester_pair = await login(
                client,
                tenant_id=tenant_id,
                username=requester.username,
                password=requester_password,
                stage="requester login",
            )
            peer_pair = await login(
                client,
                tenant_id=tenant_id,
                username=peer.username,
                password=peer_password,
                stage="peer login",
            )
            staff_pair = await login(
                client,
                tenant_id=tenant_id,
                username=staff.username,
                password=staff_password,
                stage="staff login",
            )
            outsider_pair = await login(
                client,
                tenant_id=outsider_tenant_id,
                username=outsider.username,
                password=outsider_password,
                stage="outsider login",
            )
            for pair in (requester_pair, peer_pair, staff_pair, outsider_pair):
                issued_tokens.extend(
                    [
                        (str(pair["access_token"]), TokenType.ACCESS),
                        (str(pair["refresh_token"]), TokenType.REFRESH),
                    ]
                )
            protected_values = tuple(
                value
                for value in (
                    *settings_secrets,
                    admin_password,
                    requester_password,
                    peer_password,
                    staff_password,
                    outsider_password,
                    *(token for token, _ in issued_tokens),
                )
                if value
            )
            requester_headers = auth_headers(requester_pair)
            peer_headers = auth_headers(peer_pair)
            staff_headers = auth_headers(staff_pair)
            outsider_headers = auth_headers(outsider_pair)

            created = await client.post(
                "/api/v1/customer-service/tickets",
                headers=requester_headers,
                json={
                    "subject": " 退款申请条件与到账时间 ",
                    "description": "退款申请需要满足什么条件，审核后多久可以到账？",
                },
            )
            require_status(created, 201, "ticket create")
            created_payload = assert_safe_response(created, protected_values)
            ticket_id = UUID(str(created_payload["id"]))
            if (
                created_payload.get("status") != CustomerTicketStatus.OPEN.value
                or any(
                    field in created_payload
                    for field in (
                        "tenant_id",
                        "requester_user_id",
                        "assigned_user_id",
                        "classification_confidence",
                        "classification_reason",
                    )
                )
            ):
                raise AssertionError("Created ticket state is inconsistent.")
            print("customer_ticket_create: PASS (status=201, state=open)")

            requester_list = await client.get(
                "/api/v1/customer-service/tickets",
                headers=requester_headers,
            )
            require_status(requester_list, 200, "requester ticket list")
            requester_list_payload = assert_safe_response(
                requester_list,
                protected_values,
            )
            if requester_list_payload.get("total") != 1:
                raise AssertionError("Requester ticket list is not owner scoped.")
            requester_items = requester_list_payload.get("items")
            if (
                not isinstance(requester_items, list)
                or len(requester_items) != 1
                or not isinstance(requester_items[0], dict)
                or any(
                    field in requester_items[0]
                    for field in ("tenant_id", "requester_user_id", "assigned_user_id")
                )
            ):
                raise AssertionError("Requester ticket list exposed internal identifiers.")

            for label, headers in (
                ("peer", peer_headers),
                ("outsider", outsider_headers),
            ):
                hidden = await client.get(
                    f"/api/v1/customer-service/tickets/{ticket_id}",
                    headers=headers,
                )
                require_status(hidden, 404, f"{label} ticket isolation")
                hidden_payload = assert_safe_response(hidden, protected_values)
                if require_error_code(hidden_payload) != "customer_ticket_not_found":
                    raise AssertionError(f"{label} ticket access was not hidden.")
            print("customer_ticket_isolation: PASS (peer=404, outsider=404)")

            forbidden = await client.post(
                "/api/v1/customer-service/classify",
                headers=requester_headers,
                json={"ticket_id": str(ticket_id)},
            )
            require_status(forbidden, 403, "requester classification rejection")
            forbidden_payload = assert_safe_response(forbidden, protected_values)
            if require_error_code(forbidden_payload) != "forbidden":
                raise AssertionError("Requester classification was not forbidden.")

            classified = await client.post(
                "/api/v1/customer-service/classify",
                headers=staff_headers,
                json={"ticket_id": str(ticket_id)},
            )
            require_status(classified, 200, "ticket classification")
            classified_payload = assert_safe_response(classified, protected_values)
            if (
                classified_payload.get("category") != "refund_after_sales"
                or classified_payload.get("priority") != "high"
                or classified_payload.get("status") != "in_progress"
            ):
                raise AssertionError("Ticket classification is inconsistent.")
            print("customer_ticket_classify: PASS (refund_after_sales, high)")

            generated = await client.post(
                "/api/v1/customer-service/reply-suggestions",
                headers=staff_headers,
                json={"ticket_id": str(ticket_id)},
            )
            require_status(generated, 200, "reply suggestion generation")
            generated_payload = assert_safe_response(generated, protected_values)
            suggestion_id = UUID(str(generated_payload["id"]))
            citations = generated_payload.get("citations")
            if (
                generated_payload.get("status") != ReplySuggestionStatus.DRAFT.value
                or generated_payload.get("knowledge_outcome") != "answered"
                or generated_payload.get("quality_status") != "passed"
                or not isinstance(citations, list)
                or not citations
            ):
                raise AssertionError("Knowledge-enhanced suggestion is inconsistent.")
            print("customer_reply_suggestion: PASS (knowledge=answered, quality=passed)")

            requester_draft = await client.get(
                f"/api/v1/customer-service/tickets/{ticket_id}",
                headers=requester_headers,
            )
            require_status(requester_draft, 200, "requester draft visibility")
            requester_draft_payload = assert_safe_response(
                requester_draft,
                protected_values,
            )
            requester_draft_ticket = requester_draft_payload.get("ticket")
            if (
                requester_draft_payload.get("view") != "public"
                or requester_draft_payload.get("confirmed_reply") is not None
                or "reply_suggestion" in requester_draft_payload
                or not isinstance(requester_draft_ticket, dict)
                or any(
                    field in requester_draft_ticket
                    for field in ("tenant_id", "requester_user_id", "assigned_user_id")
                )
            ):
                raise AssertionError("Requester could observe an internal draft suggestion.")
            print("customer_reply_draft_visibility: PASS (requester=draft-hidden)")

            confirmed = await client.post(
                f"/api/v1/customer-service/reply-suggestions/{suggestion_id}/confirm",
                headers=staff_headers,
                json={"final_reply": "  已核对退款政策，请按原支付渠道和审核进度耐心等待。  "},
            )
            require_status(confirmed, 200, "reply confirmation")
            confirmed_payload = assert_safe_response(confirmed, protected_values)
            suggestion_payload = confirmed_payload.get("reply_suggestion")
            ticket_payload = confirmed_payload.get("ticket")
            if (
                not isinstance(suggestion_payload, dict)
                or not isinstance(ticket_payload, dict)
                or suggestion_payload.get("status") != "confirmed"
                or suggestion_payload.get("final_reply")
                != "已核对退款政策，请按原支付渠道和审核进度耐心等待。"
                or ticket_payload.get("status") != "resolved"
            ):
                raise AssertionError("Human confirmation state is inconsistent.")
            print("customer_reply_confirm: PASS (ticket=resolved)")

            repeated = await client.post(
                f"/api/v1/customer-service/reply-suggestions/{suggestion_id}/confirm",
                headers=staff_headers,
                json={},
            )
            require_status(repeated, 200, "idempotent reply confirmation")
            repeated_payload = assert_safe_response(repeated, protected_values)
            repeated_suggestion = repeated_payload.get("reply_suggestion")
            if (
                not isinstance(repeated_suggestion, dict)
                or repeated_suggestion.get("id") != str(suggestion_id)
            ):
                raise AssertionError("Repeated confirmation was not idempotent.")

            changed = await client.post(
                f"/api/v1/customer-service/reply-suggestions/{suggestion_id}/confirm",
                headers=staff_headers,
                json={"final_reply": "确认后的不同内容"},
            )
            require_status(changed, 409, "confirmed reply mutation rejection")
            changed_payload = assert_safe_response(changed, protected_values)
            if require_error_code(changed_payload) != "reply_suggestion_already_confirmed":
                raise AssertionError("Confirmed reply mutation used an unstable error code.")

            regenerated = await client.post(
                "/api/v1/customer-service/reply-suggestions",
                headers=staff_headers,
                json={"ticket_id": str(ticket_id)},
            )
            require_status(regenerated, 409, "confirmed suggestion regeneration rejection")
            regenerated_payload = assert_safe_response(regenerated, protected_values)
            if (
                require_error_code(regenerated_payload)
                != "reply_suggestion_already_confirmed"
            ):
                raise AssertionError("Confirmed suggestion regeneration was not stable.")
            print("customer_reply_idempotency: PASS (repeat=200, mutation=409)")

            owner_detail = await client.get(
                f"/api/v1/customer-service/tickets/{ticket_id}",
                headers=requester_headers,
            )
            require_status(owner_detail, 200, "requester resolved detail")
            owner_payload = assert_safe_response(owner_detail, protected_values)
            owner_ticket = owner_payload.get("ticket")
            owner_reply = owner_payload.get("confirmed_reply")
            if (
                owner_payload.get("view") != "public"
                or "reply_suggestion" in owner_payload
                or not isinstance(owner_ticket, dict)
                or owner_ticket.get("status") != "resolved"
                or any(
                    field in owner_ticket
                    for field in ("tenant_id", "requester_user_id", "assigned_user_id")
                )
                or not isinstance(owner_reply, dict)
                or owner_reply.get("final_reply")
                != "已核对退款政策，请按原支付渠道和审核进度耐心等待。"
            ):
                raise AssertionError("Requester cannot observe the resolved ticket state.")

            async with database.session_factory() as session:
                ticket = await session.get(CustomerTicket, ticket_id)
                suggestions = list(
                    (
                        await session.scalars(
                            select(ReplySuggestion).where(
                                ReplySuggestion.ticket_id == ticket_id
                            )
                        )
                    ).all()
                )
                if (
                    ticket is None
                    or ticket.status != CustomerTicketStatus.RESOLVED
                    or len(suggestions) != 1
                    or suggestions[0].status != ReplySuggestionStatus.CONFIRMED
                ):
                    raise AssertionError("Persisted customer-service state is inconsistent.")

            for pair, headers in (
                (requester_pair, requester_headers),
                (peer_pair, peer_headers),
                (staff_pair, staff_headers),
                (outsider_pair, outsider_headers),
            ):
                await client.post(
                    "/api/v1/auth/logout",
                    headers=headers,
                    json={"refresh_token": pair["refresh_token"]},
                )
    finally:
        for token, token_type in issued_tokens:
            try:
                claims = tokens.decode(token, expected_type=token_type)
            except Exception:
                continue
            redis_key = f"auth:revoked:{claims.jti}"
            redis_keys.add(redis_key)
            await redis.delete(redis_key)

        async with database.session_factory() as session:
            if ticket_id is not None:
                await session.execute(
                    delete(ReplySuggestion).where(
                        ReplySuggestion.ticket_id == ticket_id
                    )
                )
                await session.execute(
                    delete(CustomerTicket).where(CustomerTicket.id == ticket_id)
                )
            await session.execute(delete(User).where(User.tenant_id.in_(tenant_ids)))
            await session.execute(delete(Role).where(Role.tenant_id.in_(tenant_ids)))
            await session.commit()

        counts = await fixture_counts(database, tenant_ids, ticket_id)
        redis_count = 0
        for key in redis_keys:
            redis_count += int(await redis.exists(key))
        await redis.aclose()
        await database.close()
        if any((*counts, redis_count)):
            raise AssertionError(
                "Temporary customer-service smoke fixtures were not fully cleaned."
            )
        print(
            "temporary customer-service smoke fixtures: "
            "tickets=0, suggestions=0, users=0, roles=0, redis_keys=0"
        )


if __name__ == "__main__":
    run_async(verify())
