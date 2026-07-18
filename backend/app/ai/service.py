import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from app.ai.models import AIRun, AIRunMode
from app.ai.providers.base import ChatInputMessage, ChatProvider, ProviderError
from app.ai.providers.factory import ProviderFactory
from app.ai.repository import AIRunsRepository
from app.ai.run_lifecycle import AIRunLifecycle, PreparedAIRun
from app.ai.schemas import AIRunResponse, ChatStreamRequest
from app.ai.sse import encode_sse
from app.auth.principal import Principal
from app.conversations.service import ConversationService
from app.core.errors import AppError

logger = logging.getLogger("app.ai")


@dataclass(slots=True)
class PreparedChat:
    execution: PreparedAIRun
    provider: ChatProvider
    messages: list[ChatInputMessage]


class AIChatService:
    def __init__(
        self,
        *,
        runs: AIRunsRepository,
        conversations: ConversationService,
        providers: ProviderFactory,
        history_limit: int,
    ) -> None:
        self._lifecycle = AIRunLifecycle(
            runs=runs,
            conversations=conversations,
            history_limit=history_limit,
        )
        self._providers = providers

    async def prepare(
        self,
        principal: Principal,
        request_id: str,
        request: ChatStreamRequest,
    ) -> PreparedChat:
        provider = self._providers.create(request.provider)
        execution = await self._lifecycle.start(
            principal,
            request_id=request_id,
            conversation_id=request.conversation_id,
            message=request.message,
            provider=provider.name,
            model=provider.model,
            mode=AIRunMode.CHAT,
        )
        return PreparedChat(
            execution=execution,
            provider=provider,
            messages=[
                ChatInputMessage(role=item.role.value, content=item.content)
                for item in execution.history
            ],
        )

    async def stream(
        self,
        principal: Principal,
        prepared: PreparedChat,
    ) -> AsyncIterator[str]:
        run = prepared.execution.run
        yield encode_sse(
            "metadata",
            {
                "request_id": run.request_id,
                "run_id": str(run.id),
                "conversation_id": str(run.conversation_id),
                "provider": run.provider,
                "model": run.model,
                "mode": run.mode.value,
                "user_message_id": str(prepared.execution.user_message.id),
                "user_message_position": prepared.execution.user_message.position,
            },
        )

        answer_parts: list[str] = []
        input_tokens: int | None = None
        output_tokens: int | None = None
        provider_request_id: str | None = None
        try:
            async for chunk in prepared.provider.stream(prepared.messages):
                if chunk.provider_request_id:
                    provider_request_id = chunk.provider_request_id
                if chunk.usage is not None:
                    input_tokens = chunk.usage.input_tokens
                    output_tokens = chunk.usage.output_tokens
                if chunk.delta:
                    answer_parts.append(chunk.delta)
                    yield encode_sse(
                        "token",
                        {
                            "run_id": str(run.id),
                            "delta": chunk.delta,
                        },
                    )

            answer = "".join(answer_parts).strip()
            if not answer:
                raise ProviderError(
                    code="ai_empty_response",
                    message="模型服务没有返回有效内容。",
                )
            assistant_message = await self._lifecycle.succeed(
                principal,
                prepared.execution,
                answer=answer,
                metadata={},
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                provider_request_id=provider_request_id,
            )
            yield encode_sse(
                "message_end",
                {
                    "request_id": run.request_id,
                    "run_id": str(run.id),
                    "message_id": str(assistant_message.id),
                    "message_position": assistant_message.position,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                },
            )
        except asyncio.CancelledError:
            await asyncio.shield(self._lifecycle.cancel(run))
            raise
        except ProviderError as exc:
            await self._lifecycle.fail(run, code=exc.code, message=exc.message)
            yield self._error_event(run, exc.code, exc.message)
        except AppError as exc:
            await self._lifecycle.fail(run, code=exc.code, message=exc.message)
            yield self._error_event(run, exc.code, exc.message)
        except Exception:
            logger.exception(
                "ai_stream_failed",
                extra={
                    "request_id": run.request_id,
                    "run_id": str(run.id),
                    "provider": run.provider,
                },
            )
            code = "ai_stream_failed"
            message = "AI 对话生成失败。"
            await self._lifecycle.fail(run, code=code, message=message)
            yield self._error_event(run, code, message)

    async def get_run(self, principal: Principal, run_id: UUID) -> AIRunResponse:
        return await self._lifecycle.get_run(principal, run_id)

    @staticmethod
    def _error_event(run: AIRun, code: str, message: str) -> str:
        return encode_sse(
            "error",
            {
                "request_id": run.request_id,
                "run_id": str(run.id),
                "code": code,
                "message": message,
            },
        )
