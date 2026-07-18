from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import status

from app.ai.models import AIRun, AIRunMode, AIRunStatus
from app.ai.repository import AIRunsRepository, DuplicateAIRunError
from app.ai.schemas import AIRunResponse
from app.auth.principal import Principal
from app.conversations.models import MessageRole
from app.conversations.schemas import MessageResponse
from app.conversations.service import ConversationService
from app.core.errors import AppError


@dataclass(slots=True)
class PreparedAIRun:
    run: AIRun
    user_message: MessageResponse
    history: list[MessageResponse]


class AIRunLifecycle:
    def __init__(
        self,
        *,
        runs: AIRunsRepository,
        conversations: ConversationService,
        history_limit: int,
    ) -> None:
        self._runs = runs
        self._conversations = conversations
        self._history_limit = history_limit

    async def start(
        self,
        principal: Principal,
        *,
        request_id: str,
        conversation_id: UUID,
        message: str,
        provider: str,
        model: str,
        mode: AIRunMode,
    ) -> PreparedAIRun:
        await self._conversations.get(principal, conversation_id)
        run = AIRun(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            conversation_id=conversation_id,
            request_id=request_id,
            provider=provider,
            model=model,
            mode=mode,
            status=AIRunStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        try:
            await self._runs.create(run)
        except DuplicateAIRunError as exc:
            existing = await self._runs.get_by_request_id(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                request_id=request_id,
            )
            raise AppError(
                code="ai_request_conflict",
                message="相同请求编号的 AI 任务已经存在。",
                status_code=status.HTTP_409_CONFLICT,
                details={"run_id": str(existing.id)} if existing else None,
            ) from exc

        try:
            user_message = await self._conversations.append_message(
                principal,
                conversation_id,
                role=MessageRole.USER,
                content=message,
                metadata={"ai_run_id": str(run.id), "mode": mode.value},
            )
        except AppError as exc:
            await self.fail(run, code=exc.code, message=exc.message)
            raise

        run.prompt_message_id = user_message.id
        await self._runs.save(run)
        history = await self._conversations.recent_messages(
            principal,
            conversation_id,
            limit=self._history_limit,
        )
        return PreparedAIRun(run=run, user_message=user_message, history=history)

    async def succeed(
        self,
        principal: Principal,
        prepared: PreparedAIRun,
        *,
        answer: str,
        metadata: dict[str, object],
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        provider_request_id: str | None = None,
    ) -> MessageResponse:
        run = prepared.run
        assistant_message = await self._conversations.append_message(
            principal,
            run.conversation_id,
            role=MessageRole.ASSISTANT,
            content=answer,
            metadata={
                "ai_run_id": str(run.id),
                "provider": run.provider,
                "model": run.model,
                "mode": run.mode.value,
                **metadata,
            },
        )
        run.status = AIRunStatus.SUCCEEDED
        run.response_message_id = assistant_message.id
        run.provider_request_id = provider_request_id
        run.input_tokens = input_tokens
        run.output_tokens = output_tokens
        run.completed_at = datetime.now(UTC)
        run.error_code = None
        run.error_message = None
        await self._runs.save(run)
        return assistant_message

    async def fail(self, run: AIRun, *, code: str, message: str) -> None:
        run.status = AIRunStatus.FAILED
        run.error_code = code[:100]
        run.error_message = message[:500]
        run.completed_at = datetime.now(UTC)
        await self._runs.save(run)

    async def cancel(self, run: AIRun) -> None:
        run.status = AIRunStatus.CANCELLED
        run.error_code = "ai_stream_cancelled"
        run.error_message = "客户端已断开 AI 流式请求。"
        run.completed_at = datetime.now(UTC)
        await self._runs.save(run)

    async def get_run(self, principal: Principal, run_id: UUID) -> AIRunResponse:
        run = await self._runs.get_owned(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            run_id=run_id,
        )
        if run is None:
            raise AppError(
                code="ai_run_not_found",
                message="AI 运行记录不存在。",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return AIRunResponse.from_entity(run)
