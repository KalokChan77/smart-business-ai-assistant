import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError

from app.auth.principal import Principal
from app.auth.security import PasswordService
from app.core.config import Settings
from app.customer_service.models import (
    CustomerServiceKnowledgeOutcome,
    CustomerTicket,
    CustomerTicketCategory,
    CustomerTicketPriority,
    CustomerTicketStatus,
    ReplyQualityStatus,
    ReplySuggestion,
    ReplySuggestionStatus,
)
from app.customer_service.ports import (
    CustomerServiceCitation,
    CustomerServiceKnowledgeResult,
    CustomerServiceRepositoryError,
    CustomerServiceWorkflowResult,
    CustomerTicketNotActionableError,
    ReplySuggestionAlreadyConfirmedError,
    TicketClassification,
)
from app.customer_service.repository import CustomerServiceRepository
from app.db.session import Database
from app.users.models import Role, User
from app.users.repository import UsersRepository
from app.users.schemas import UserCreateRequest
from app.users.service import UserService

pytestmark = pytest.mark.integration


def principal_from_user(user, *roles: str) -> Principal:
    return Principal(
        user_id=user.id,
        tenant_id=user.tenant_id,
        username=user.username,
        email=user.email,
        roles=frozenset(roles),
    )


def workflow_result(
    *,
    reply: str,
    category: CustomerTicketCategory = CustomerTicketCategory.REFUND_AFTER_SALES,
) -> CustomerServiceWorkflowResult:
    return CustomerServiceWorkflowResult(
        classification=TicketClassification(
            category=category,
            priority=CustomerTicketPriority.HIGH,
            confidence=90,
            reason="命中退款与到账相关关键词。",
        ),
        suggested_reply=reply,
        knowledge=CustomerServiceKnowledgeResult(
            outcome=CustomerServiceKnowledgeOutcome.ANSWERED,
            answer="退款按原支付渠道退回。",
            citations=(
                CustomerServiceCitation(
                    rank=1,
                    document_name="退款政策",
                    excerpt="退款按原支付渠道退回。",
                    score=0.9,
                ),
            ),
        ),
        quality_status=ReplyQualityStatus.PASSED,
        quality_notes=(),
        workflow_version="customer-service-v1",
    )


async def create_ticket(
    database: Database,
    principal: Principal,
    *,
    suffix: str,
) -> CustomerTicket:
    async with database.session_factory() as session:
        return await CustomerServiceRepository(session).create_ticket(
            CustomerTicket(
                tenant_id=principal.tenant_id,
                requester_user_id=principal.user_id,
                subject=f"退款到账咨询-{suffix}",
                description="订单退款通常需要多久才能到账？",
                status=CustomerTicketStatus.OPEN,
                priority=CustomerTicketPriority.NORMAL,
            )
        )


async def save_concurrently(
    database: Database,
    *,
    tenant_id: UUID,
    actor_user_id: UUID,
    ticket_id: UUID,
    reply: str,
) -> ReplySuggestion:
    async with database.session_factory() as session:
        _, suggestion = await CustomerServiceRepository(
            session
        ).save_generated_suggestion(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            ticket_id=ticket_id,
            result=workflow_result(reply=reply),
        )
        return suggestion


async def confirm_concurrently(
    database: Database,
    *,
    tenant_id: UUID,
    actor_user_id: UUID,
    suggestion_id: UUID,
    final_reply: str,
):
    async with database.session_factory() as session:
        return await CustomerServiceRepository(session).confirm_suggestion(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            suggestion_id=suggestion_id,
            final_reply=final_reply,
        )


async def test_customer_service_repository_enforces_scope_upsert_and_confirmation() -> None:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("DATABASE_URL is not configured")

    tenant_a = uuid4()
    tenant_b = uuid4()
    tenant_ids = (tenant_a, tenant_b)
    suffix = uuid4().hex[:8]
    tracked_ticket_ids: set[UUID] = set()
    database = Database.create(settings.database_url.get_secret_value())
    try:
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            admin_a = await users.bootstrap_admin(
                tenant_id=tenant_a,
                username=f"cs-admin-a-{suffix}",
                email=f"cs-admin-a-{suffix}@example.test",
                password="integration-password",
            )
        admin_a_principal = principal_from_user(admin_a, "admin")
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            requester = await users.create_user(
                admin_a_principal,
                UserCreateRequest(
                    username=f"cs-requester-{suffix}",
                    email=f"cs-requester-{suffix}@example.test",
                    password="integration-password",
                    role_codes={"user"},
                ),
            )
            peer = await users.create_user(
                admin_a_principal,
                UserCreateRequest(
                    username=f"cs-peer-{suffix}",
                    email=f"cs-peer-{suffix}@example.test",
                    password="integration-password",
                    role_codes={"user"},
                ),
            )
            staff = await users.create_user(
                admin_a_principal,
                UserCreateRequest(
                    username=f"cs-staff-{suffix}",
                    email=f"cs-staff-{suffix}@example.test",
                    password="integration-password",
                    role_codes={"customer_service"},
                ),
            )
        async with database.session_factory() as session:
            users = UserService(UsersRepository(session), PasswordService())
            admin_b = await users.bootstrap_admin(
                tenant_id=tenant_b,
                username=f"cs-admin-b-{suffix}",
                email=f"cs-admin-b-{suffix}@example.test",
                password="integration-password",
            )

        requester_principal = principal_from_user(requester, "user")
        peer_principal = principal_from_user(peer, "user")
        staff_principal = principal_from_user(staff, "customer_service")
        outsider_principal = principal_from_user(admin_b, "admin")

        ticket = await create_ticket(
            database,
            requester_principal,
            suffix=f"owner-{suffix}",
        )
        tracked_ticket_ids.add(ticket.id)

        async with database.session_factory() as session:
            repository = CustomerServiceRepository(session)
            owner_detail = await repository.get_visible_detail(
                tenant_id=requester_principal.tenant_id,
                user_id=requester_principal.user_id,
                staff=False,
                ticket_id=ticket.id,
            )
            peer_detail = await repository.get_visible_detail(
                tenant_id=peer_principal.tenant_id,
                user_id=peer_principal.user_id,
                staff=False,
                ticket_id=ticket.id,
            )
            staff_detail = await repository.get_visible_detail(
                tenant_id=staff_principal.tenant_id,
                user_id=staff_principal.user_id,
                staff=True,
                ticket_id=ticket.id,
            )
            outsider_detail = await repository.get_visible_detail(
                tenant_id=outsider_principal.tenant_id,
                user_id=outsider_principal.user_id,
                staff=True,
                ticket_id=ticket.id,
            )
            assert owner_detail is not None
            assert peer_detail is None
            assert staff_detail is not None
            assert outsider_detail is None

        classification = workflow_result(reply="unused").classification
        async with database.session_factory() as session:
            classified = await CustomerServiceRepository(session).classify_ticket(
                tenant_id=staff_principal.tenant_id,
                actor_user_id=staff_principal.user_id,
                ticket_id=ticket.id,
                classification=classification,
            )
            assert classified.status == CustomerTicketStatus.IN_PROGRESS
            assert classified.category == CustomerTicketCategory.REFUND_AFTER_SALES
            assert classified.assigned_user_id == staff_principal.user_id

        async with database.session_factory() as session:
            repository = CustomerServiceRepository(session)
            _, first = await repository.save_generated_suggestion(
                tenant_id=staff_principal.tenant_id,
                actor_user_id=staff_principal.user_id,
                ticket_id=ticket.id,
                result=workflow_result(reply="第一版建议"),
            )
            _, second = await repository.save_generated_suggestion(
                tenant_id=staff_principal.tenant_id,
                actor_user_id=staff_principal.user_id,
                ticket_id=ticket.id,
                result=workflow_result(reply="第二版建议"),
            )
            assert second.id == first.id
            assert second.created_at == first.created_at
            assert second.suggested_reply == "第二版建议"

        async with database.session_factory() as session:
            requester_draft_detail = await CustomerServiceRepository(
                session
            ).get_visible_detail(
                tenant_id=requester_principal.tenant_id,
                user_id=requester_principal.user_id,
                staff=False,
                ticket_id=ticket.id,
            )
            staff_draft_detail = await CustomerServiceRepository(
                session
            ).get_visible_detail(
                tenant_id=staff_principal.tenant_id,
                user_id=staff_principal.user_id,
                staff=True,
                ticket_id=ticket.id,
            )
            assert requester_draft_detail is not None
            assert requester_draft_detail[1] is None
            assert staff_draft_detail is not None
            assert staff_draft_detail[1] is not None

        concurrent_ticket = await create_ticket(
            database,
            requester_principal,
            suffix=f"concurrent-{suffix}",
        )
        tracked_ticket_ids.add(concurrent_ticket.id)
        concurrent_results = await asyncio.gather(
            save_concurrently(
                database,
                tenant_id=staff_principal.tenant_id,
                actor_user_id=staff_principal.user_id,
                ticket_id=concurrent_ticket.id,
                reply="并发建议 A",
            ),
            save_concurrently(
                database,
                tenant_id=staff_principal.tenant_id,
                actor_user_id=staff_principal.user_id,
                ticket_id=concurrent_ticket.id,
                reply="并发建议 B",
            ),
        )
        assert concurrent_results[0].id == concurrent_results[1].id
        async with database.session_factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(ReplySuggestion)
                .where(ReplySuggestion.ticket_id == concurrent_ticket.id)
            )
            assert count == 1

        lock_order_ticket = await create_ticket(
            database,
            requester_principal,
            suffix=f"lock-order-{suffix}",
        )
        tracked_ticket_ids.add(lock_order_ticket.id)
        async with database.session_factory() as session:
            _, lock_order_suggestion = await CustomerServiceRepository(
                session
            ).save_generated_suggestion(
                tenant_id=staff_principal.tenant_id,
                actor_user_id=staff_principal.user_id,
                ticket_id=lock_order_ticket.id,
                result=workflow_result(reply="并发前草稿"),
            )

        concurrent_transition_results = await asyncio.wait_for(
            asyncio.gather(
                save_concurrently(
                    database,
                    tenant_id=staff_principal.tenant_id,
                    actor_user_id=staff_principal.user_id,
                    ticket_id=lock_order_ticket.id,
                    reply="并发重新生成草稿",
                ),
                confirm_concurrently(
                    database,
                    tenant_id=staff_principal.tenant_id,
                    actor_user_id=staff_principal.user_id,
                    suggestion_id=lock_order_suggestion.id,
                    final_reply="并发人工确认回复",
                ),
                return_exceptions=True,
            ),
            timeout=10,
        )
        assert not any(
            isinstance(result, CustomerServiceRepositoryError)
            for result in concurrent_transition_results
        )
        assert not isinstance(concurrent_transition_results[1], Exception)
        assert isinstance(
            concurrent_transition_results[0],
            (ReplySuggestion, ReplySuggestionAlreadyConfirmedError),
        )
        async with database.session_factory() as session:
            final_lock_order_suggestion = await session.scalar(
                select(ReplySuggestion).where(
                    ReplySuggestion.id == lock_order_suggestion.id
                )
            )
            final_lock_order_ticket = await session.get(
                CustomerTicket,
                lock_order_ticket.id,
            )
            assert final_lock_order_suggestion is not None
            assert final_lock_order_suggestion.status == ReplySuggestionStatus.CONFIRMED
            assert final_lock_order_suggestion.final_reply == "并发人工确认回复"
            assert final_lock_order_ticket is not None
            assert final_lock_order_ticket.status == CustomerTicketStatus.RESOLVED

        async with database.session_factory() as session:
            repository = CustomerServiceRepository(session)
            confirmed_ticket, confirmed = await repository.confirm_suggestion(
                tenant_id=staff_principal.tenant_id,
                actor_user_id=staff_principal.user_id,
                suggestion_id=first.id,
                final_reply="客服人工编辑后的最终回复",
            )
            assert confirmed.status == ReplySuggestionStatus.CONFIRMED
            assert confirmed.final_reply == "客服人工编辑后的最终回复"
            assert confirmed_ticket.status == CustomerTicketStatus.RESOLVED

        async with database.session_factory() as session:
            requester_confirmed_detail = await CustomerServiceRepository(
                session
            ).get_visible_detail(
                tenant_id=requester_principal.tenant_id,
                user_id=requester_principal.user_id,
                staff=False,
                ticket_id=ticket.id,
            )
            assert requester_confirmed_detail is not None
            assert requester_confirmed_detail[1] is not None
            assert (
                requester_confirmed_detail[1].status
                == ReplySuggestionStatus.CONFIRMED
            )

        async with database.session_factory() as session:
            repeated_ticket, repeated = await CustomerServiceRepository(
                session
            ).confirm_suggestion(
                tenant_id=staff_principal.tenant_id,
                actor_user_id=staff_principal.user_id,
                suggestion_id=first.id,
                final_reply=None,
            )
            assert repeated.id == first.id
            assert repeated_ticket.status == CustomerTicketStatus.RESOLVED

        async with database.session_factory() as session:
            with pytest.raises(ReplySuggestionAlreadyConfirmedError):
                await CustomerServiceRepository(session).confirm_suggestion(
                    tenant_id=staff_principal.tenant_id,
                    actor_user_id=staff_principal.user_id,
                    suggestion_id=first.id,
                    final_reply="不同的二次修改",
                )

        async with database.session_factory() as session:
            with pytest.raises(ReplySuggestionAlreadyConfirmedError):
                await CustomerServiceRepository(session).save_generated_suggestion(
                    tenant_id=staff_principal.tenant_id,
                    actor_user_id=staff_principal.user_id,
                    ticket_id=ticket.id,
                    result=workflow_result(reply="确认后重新生成"),
                )

        async with database.session_factory() as session:
            with pytest.raises(CustomerTicketNotActionableError):
                await CustomerServiceRepository(session).classify_ticket(
                    tenant_id=staff_principal.tenant_id,
                    actor_user_id=staff_principal.user_id,
                    ticket_id=ticket.id,
                    classification=classification,
                )

        constraint_ticket = await create_ticket(
            database,
            requester_principal,
            suffix=f"constraint-{suffix}",
        )
        tracked_ticket_ids.add(constraint_ticket.id)
        invalid_ticket = {
            "id": uuid4(),
            "tenant_id": tenant_a,
            "requester_user_id": requester_principal.user_id,
            "subject": "非法置信度",
            "description": "数据库约束测试",
            "status": CustomerTicketStatus.IN_PROGRESS.value,
            "priority": CustomerTicketPriority.NORMAL.value,
            "classification_confidence": 101,
        }
        invalid_suggestion = {
            "id": uuid4(),
            "ticket_id": constraint_ticket.id,
            "tenant_id": tenant_a,
            "category": CustomerTicketCategory.OTHER.value,
            "status": ReplySuggestionStatus.CONFIRMED.value,
            "suggested_reply": "建议",
            "knowledge_outcome": CustomerServiceKnowledgeOutcome.NO_MATCH.value,
            "citations": [],
            "quality_status": ReplyQualityStatus.NEEDS_REVIEW.value,
            "quality_notes": ["需要人工复核"],
            "workflow_version": "customer-service-v1",
            "generated_by_user_id": staff_principal.user_id,
            "confirmed_by_user_id": staff_principal.user_id,
            "confirmed_at": datetime.now(UTC),
        }
        cross_tenant_requester_ticket = {
            "id": uuid4(),
            "tenant_id": tenant_a,
            "requester_user_id": outsider_principal.user_id,
            "subject": "跨租户请求者",
            "description": "数据库必须拒绝跨租户请求者。",
            "status": CustomerTicketStatus.OPEN.value,
            "priority": CustomerTicketPriority.NORMAL.value,
        }
        cross_tenant_assignee_ticket = {
            "id": uuid4(),
            "tenant_id": tenant_a,
            "requester_user_id": requester_principal.user_id,
            "assigned_user_id": outsider_principal.user_id,
            "subject": "跨租户处理人",
            "description": "数据库必须拒绝跨租户处理人。",
            "status": CustomerTicketStatus.IN_PROGRESS.value,
            "priority": CustomerTicketPriority.NORMAL.value,
        }
        cross_tenant_actor_suggestion = {
            "id": uuid4(),
            "ticket_id": constraint_ticket.id,
            "tenant_id": tenant_a,
            "category": CustomerTicketCategory.OTHER.value,
            "status": ReplySuggestionStatus.DRAFT.value,
            "suggested_reply": "建议",
            "knowledge_outcome": CustomerServiceKnowledgeOutcome.NO_MATCH.value,
            "citations": [],
            "quality_status": ReplyQualityStatus.NEEDS_REVIEW.value,
            "quality_notes": ["需要人工复核"],
            "workflow_version": "customer-service-v1",
            "generated_by_user_id": outsider_principal.user_id,
        }
        confirmed_without_actor = {
            "id": uuid4(),
            "ticket_id": constraint_ticket.id,
            "tenant_id": tenant_a,
            "category": CustomerTicketCategory.OTHER.value,
            "status": ReplySuggestionStatus.CONFIRMED.value,
            "suggested_reply": "建议",
            "final_reply": "最终回复",
            "knowledge_outcome": CustomerServiceKnowledgeOutcome.NO_MATCH.value,
            "citations": [],
            "quality_status": ReplyQualityStatus.NEEDS_REVIEW.value,
            "quality_notes": ["需要人工复核"],
            "workflow_version": "customer-service-v1",
            "generated_by_user_id": staff_principal.user_id,
            "confirmed_by_user_id": None,
            "confirmed_at": datetime.now(UTC),
        }
        for table, row in (
            (CustomerTicket.__table__, invalid_ticket),
            (ReplySuggestion.__table__, invalid_suggestion),
            (CustomerTicket.__table__, cross_tenant_requester_ticket),
            (CustomerTicket.__table__, cross_tenant_assignee_ticket),
            (ReplySuggestion.__table__, cross_tenant_actor_suggestion),
            (ReplySuggestion.__table__, confirmed_without_actor),
        ):
            async with database.session_factory() as session:
                with pytest.raises(IntegrityError):
                    await session.execute(insert(table).values(**row))
                    await session.commit()
                await session.rollback()
    finally:
        async with database.session_factory() as session:
            await session.execute(
                delete(ReplySuggestion).where(
                    ReplySuggestion.ticket_id.in_(tracked_ticket_ids)
                )
            )
            await session.execute(
                delete(CustomerTicket).where(CustomerTicket.id.in_(tracked_ticket_ids))
            )
            await session.execute(delete(User).where(User.tenant_id.in_(tenant_ids)))
            await session.execute(delete(Role).where(Role.tenant_id.in_(tenant_ids)))
            await session.commit()
            remaining_tickets = await session.scalar(
                select(func.count())
                .select_from(CustomerTicket)
                .where(CustomerTicket.id.in_(tracked_ticket_ids))
            )
            remaining_suggestions = await session.scalar(
                select(func.count())
                .select_from(ReplySuggestion)
                .where(ReplySuggestion.ticket_id.in_(tracked_ticket_ids))
            )
            assert remaining_tickets == 0
            assert remaining_suggestions == 0
        await database.close()
