import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.ai.models import AIRun, AIRunStatus
from app.ai.providers.base import ChatChunk, ProviderError, TokenUsage
from app.ai.repository import DuplicateAIRunError
from app.ai.schemas import ChatStreamRequest
from app.ai.service import AIChatService
from app.auth.principal import Principal
from app.conversations.models import MessageRole
from app.conversations.schemas import (
    ConversationResponse,
    MessageResponse,
)
from app.core.errors import AppError


class FakeAIRunsRepository:
    def __init__(self) -> None:
        self.runs: dict[UUID, AIRun] = {}

    async def create(self, run: AIRun) -> None:
        if any(
            item.tenant_id == run.tenant_id
            and item.user_id == run.user_id
            and item.request_id == run.request_id
            for item in self.runs.values()
        ):
            raise DuplicateAIRunError
        now = datetime.now(UTC)
        run.id = run.id or uuid4()
        run.created_at = now
        run.updated_at = now
        run.started_at = run.started_at or now
        self.runs[run.id] = run

    async def save(self, run: AIRun) -> None:
        run.updated_at = datetime.now(UTC)
        self.runs[run.id] = run

    async def get_owned(
        self, *, tenant_id: UUID, user_id: UUID, run_id: UUID
    ) -> AIRun | None:
        run = self.runs.get(run_id)
        if run is None or run.tenant_id != tenant_id or run.user_id != user_id:
            return None
        return run

    async def get_by_request_id(
        self, *, tenant_id: UUID, user_id: UUID, request_id: str
    ) -> AIRun | None:
        return next(
            (
                item
                for item in self.runs.values()
                if item.tenant_id == tenant_id
                and item.user_id == user_id
                and item.request_id == request_id
            ),
            None,
        )


class FakeConversationService:
    def __init__(self, principal: Principal) -> None:
        self.principal = principal
        now = datetime.now(UTC)
        self.conversation = ConversationResponse(
            id=uuid4(),
            title="AI 测试会话",
            last_message_at=None,
            created_at=now,
            updated_at=now,
        )
        self.messages: list[MessageResponse] = []

    async def get(
        self, principal: Principal, conversation_id: UUID
    ) -> ConversationResponse:
        self._require_owner(principal, conversation_id)
        return self.conversation

    async def append_message(
        self,
        principal: Principal,
        conversation_id: UUID,
        *,
        role: MessageRole,
        content: str,
        metadata: dict[str, object] | None = None,
    ) -> MessageResponse:
        self._require_owner(principal, conversation_id)
        message = MessageResponse(
            id=uuid4(),
            position=len(self.messages) + 1,
            role=role,
            content=content.strip(),
            metadata=dict(metadata or {}),
            created_at=datetime.now(UTC),
        )
        self.messages.append(message)
        return message

    async def recent_messages(
        self,
        principal: Principal,
        conversation_id: UUID,
        *,
        limit: int,
    ) -> list[MessageResponse]:
        self._require_owner(principal, conversation_id)
        return self.messages[-limit:]

    def _require_owner(self, principal: Principal, conversation_id: UUID) -> None:
        if principal != self.principal or conversation_id != self.conversation.id:
            raise AppError(
                code="conversation_not_found",
                message="会话不存在。",
                status_code=404,
            )


class FakeProviderFactory:
    def __init__(self, provider) -> None:
        self.provider = provider

    def create(self, requested=None):
        return self.provider


class SuccessProvider:
    name = "deepseek"
    model = "deepseek-chat"

    async def stream(self, messages):
        assert messages[-1].content == "请介绍平台"
        yield ChatChunk(delta="平台", provider_request_id="provider-1")
        yield ChatChunk(
            delta="支持 AI 对话。",
            finish_reason="stop",
            provider_request_id="provider-1",
            usage=TokenUsage(input_tokens=8, output_tokens=5),
        )


class FailingProvider:
    name = "deepseek"
    model = "deepseek-chat"

    async def stream(self, messages):
        yield ChatChunk(delta="半截")
        raise ProviderError(
            code="ai_provider_unavailable",
            message="模型服务暂时不可用。",
        )


class BlockingProvider:
    name = "dashscope"
    model = "qwen-plus"

    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def stream(self, messages):
        self.started.set()
        await asyncio.Event().wait()
        yield ChatChunk(delta="unreachable")


def make_principal() -> Principal:
    return Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        username="ai-user",
        email="ai-user@example.test",
        roles=frozenset({"user"}),
    )


def parse_event(frame: str) -> tuple[str, dict[str, object]]:
    lines = frame.strip().splitlines()
    return lines[0].removeprefix("event: "), json.loads(
        lines[1].removeprefix("data: ")
    )


async def prepare_service(provider):
    principal = make_principal()
    runs = FakeAIRunsRepository()
    conversations = FakeConversationService(principal)
    service = AIChatService(
        runs=runs,
        conversations=conversations,
        providers=FakeProviderFactory(provider),
        history_limit=50,
    )
    request = ChatStreamRequest(
        conversation_id=conversations.conversation.id,
        message=" 请介绍平台 ",
    )
    prepared = await service.prepare(principal, "request-ai-1", request)
    return service, principal, runs, conversations, prepared, request


async def test_ai_stream_success_persists_complete_assistant_once() -> None:
    service, principal, runs, conversations, prepared, _ = await prepare_service(
        SuccessProvider()
    )
    frames = [frame async for frame in service.stream(principal, prepared)]
    events = [parse_event(frame) for frame in frames]

    assert [name for name, _ in events] == [
        "metadata",
        "token",
        "token",
        "message_end",
    ]
    assert [item.role for item in conversations.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]
    assert conversations.messages[-1].content == "平台支持 AI 对话。"
    run = runs.runs[prepared.execution.run.id]
    assert run.status == AIRunStatus.SUCCEEDED
    assert run.prompt_message_id == conversations.messages[0].id
    assert run.response_message_id == conversations.messages[1].id
    assert run.input_tokens == 8
    assert run.output_tokens == 5
    assert run.error_code is None


async def test_ai_stream_provider_failure_keeps_only_user_message() -> None:
    service, principal, runs, conversations, prepared, _ = await prepare_service(
        FailingProvider()
    )
    events = [parse_event(frame) async for frame in service.stream(principal, prepared)]

    assert [name for name, _ in events] == ["metadata", "token", "error"]
    assert len(conversations.messages) == 1
    assert conversations.messages[0].role == MessageRole.USER
    run = runs.runs[prepared.execution.run.id]
    assert run.status == AIRunStatus.FAILED
    assert run.error_code == "ai_provider_unavailable"
    assert run.response_message_id is None


async def test_ai_stream_cancellation_marks_run_cancelled() -> None:
    provider = BlockingProvider()
    service, principal, runs, conversations, prepared, _ = await prepare_service(provider)
    stream = service.stream(principal, prepared)
    assert parse_event(await anext(stream))[0] == "metadata"

    pending = asyncio.create_task(anext(stream))
    await provider.started.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending

    assert len(conversations.messages) == 1
    run = runs.runs[prepared.execution.run.id]
    assert run.status == AIRunStatus.CANCELLED
    assert run.error_code == "ai_stream_cancelled"


async def test_duplicate_request_id_does_not_duplicate_user_message() -> None:
    service, principal, _, conversations, _, request = await prepare_service(
        SuccessProvider()
    )
    with pytest.raises(AppError) as captured:
        await service.prepare(principal, "request-ai-1", request)

    assert captured.value.code == "ai_request_conflict"
    assert len(conversations.messages) == 1


async def test_ai_run_is_owner_scoped() -> None:
    service, _, _, _, prepared, _ = await prepare_service(SuccessProvider())
    foreign = make_principal()
    with pytest.raises(AppError) as captured:
        await service.get_run(foreign, prepared.execution.run.id)
    assert captured.value.code == "ai_run_not_found"
