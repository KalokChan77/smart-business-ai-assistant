import asyncio
import inspect
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.errors import GraphRecursionError

from app.agent.graph import AgentGraphFactory
from app.agent.model_factory import AgentModelFactory
from app.agent.schemas import AgentStreamRequest
from app.ai.models import AIRun, AIRunMode
from app.ai.repository import AIRunsRepository
from app.ai.run_lifecycle import AIRunLifecycle, PreparedAIRun
from app.ai.sse import encode_sse
from app.auth.principal import Principal
from app.conversations.models import MessageRole
from app.conversations.service import ConversationService
from app.core.errors import AppError

logger = logging.getLogger("app.agent")


@dataclass(slots=True)
class PreparedAgent:
    execution: PreparedAIRun
    graph: object
    messages: list[BaseMessage]
    tool_names: tuple[str, ...]


class AgentService:
    def __init__(
        self,
        *,
        runs: AIRunsRepository,
        conversations: ConversationService,
        models: AgentModelFactory,
        graphs: AgentGraphFactory,
        history_limit: int,
        recursion_limit: int,
    ) -> None:
        self._lifecycle = AIRunLifecycle(
            runs=runs,
            conversations=conversations,
            history_limit=history_limit,
        )
        self._models = models
        self._graphs = graphs
        self._recursion_limit = recursion_limit

    async def prepare(
        self,
        principal: Principal,
        request_id: str,
        request: AgentStreamRequest,
    ) -> PreparedAgent:
        binding = self._models.create(request.provider)
        execution = await self._lifecycle.start(
            principal,
            request_id=request_id,
            conversation_id=request.conversation_id,
            message=request.message,
            provider=binding.provider,
            model=binding.model,
            mode=AIRunMode.AGENT,
        )
        return PreparedAgent(
            execution=execution,
            graph=self._graphs.create(binding.chat_model),
            messages=self._to_langchain_messages(execution.history),
            tool_names=self._graphs.tool_names,
        )

    async def stream(
        self,
        principal: Principal,
        prepared: PreparedAgent,
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
                "tools": list(prepared.tool_names),
                "user_message_id": str(prepared.execution.user_message.id),
                "user_message_position": prepared.execution.user_message.position,
            },
        )

        final_answer = ""
        emitted_token = False
        tool_names: list[str] = []
        input_tokens = 0
        output_tokens = 0
        has_usage = False
        provider_request_id: str | None = None
        try:
            event_stream = prepared.graph.astream_events(
                {"messages": prepared.messages},
                config={"recursion_limit": self._recursion_limit},
                version="v2",
            )
            if inspect.isawaitable(event_stream):
                event_stream = await event_stream
            async for event in event_stream:
                event_type = event.get("event")
                event_name = event.get("name")
                event_data = event.get("data") or {}
                metadata = event.get("metadata") or {}

                if (
                    event_type == "on_chat_model_stream"
                    and metadata.get("langgraph_node") == "model"
                ):
                    delta = self._message_text(event_data.get("chunk"))
                    if delta:
                        emitted_token = True
                        yield encode_sse(
                            "token",
                            {"run_id": str(run.id), "delta": delta},
                        )
                    continue

                if event_type == "on_chat_model_end" and metadata.get(
                    "langgraph_node"
                ) == "model":
                    message = event_data.get("output")
                    if isinstance(message, AIMessage):
                        usage = message.usage_metadata or {}
                        if usage:
                            has_usage = True
                            input_tokens += int(usage.get("input_tokens") or 0)
                            output_tokens += int(usage.get("output_tokens") or 0)
                        response_metadata = message.response_metadata or {}
                        provider_request_id = (
                            response_metadata.get("id")
                            or response_metadata.get("request_id")
                            or provider_request_id
                        )
                        if not message.tool_calls:
                            answer = self._message_text(message).strip()
                            if answer:
                                final_answer = answer
                    continue

                if event_type == "on_tool_start" and event_name in prepared.tool_names:
                    tool_names.append(str(event_name))
                    yield encode_sse(
                        "tool_start",
                        {
                            "run_id": str(run.id),
                            "tool": str(event_name),
                            "input": self._safe_event_value(event_data.get("input")),
                        },
                    )
                    continue

                if event_type == "on_tool_end" and event_name in prepared.tool_names:
                    yield encode_sse(
                        "tool_end",
                        {
                            "run_id": str(run.id),
                            "tool": str(event_name),
                            "output": self._safe_event_value(
                                event_data.get("output")
                            ),
                        },
                    )

            if not final_answer:
                raise AppError(
                    code="agent_empty_response",
                    message="Agent 没有返回有效的最终回答。",
                    status_code=502,
                )
            if not emitted_token:
                yield encode_sse(
                    "token",
                    {"run_id": str(run.id), "delta": final_answer},
                )
            assistant_message = await self._lifecycle.succeed(
                principal,
                prepared.execution,
                answer=final_answer,
                metadata={
                    "tools": list(dict.fromkeys(tool_names)),
                    "tool_call_count": len(tool_names),
                },
                input_tokens=input_tokens if has_usage else None,
                output_tokens=output_tokens if has_usage else None,
                provider_request_id=provider_request_id,
            )
            yield encode_sse(
                "message_end",
                {
                    "request_id": run.request_id,
                    "run_id": str(run.id),
                    "message_id": str(assistant_message.id),
                    "message_position": assistant_message.position,
                    "tool_call_count": len(tool_names),
                    "input_tokens": input_tokens if has_usage else None,
                    "output_tokens": output_tokens if has_usage else None,
                },
            )
        except asyncio.CancelledError:
            await asyncio.shield(self._lifecycle.cancel(run))
            raise
        except GraphRecursionError:
            code = "agent_recursion_limit"
            message = "Agent 工具调用次数超过限制。"
            await self._lifecycle.fail(run, code=code, message=message)
            yield self._error_event(run, code, message)
        except AppError as exc:
            await self._lifecycle.fail(run, code=exc.code, message=exc.message)
            yield self._error_event(run, exc.code, exc.message)
        except Exception:
            logger.exception(
                "agent_stream_failed",
                extra={
                    "request_id": run.request_id,
                    "run_id": str(run.id),
                    "provider": run.provider,
                },
            )
            code = "agent_execution_failed"
            message = "Agent 执行失败。"
            await self._lifecycle.fail(run, code=code, message=message)
            yield self._error_event(run, code, message)

    @staticmethod
    def _to_langchain_messages(history) -> list[BaseMessage]:
        messages: list[BaseMessage] = []
        for item in history:
            if item.role == MessageRole.USER:
                messages.append(HumanMessage(content=item.content))
            elif item.role == MessageRole.ASSISTANT:
                messages.append(AIMessage(content=item.content))
            elif item.role == MessageRole.SYSTEM:
                messages.append(SystemMessage(content=item.content))
        return messages

    @staticmethod
    def _message_text(message: object) -> str:
        if message is None:
            return ""
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
            return "".join(parts)
        text = getattr(message, "text", "")
        if isinstance(text, str):
            return text
        return ""

    @classmethod
    def _safe_event_value(cls, value: object) -> object:
        if isinstance(value, ToolMessage):
            return cls._message_text(value)[:2000]
        if isinstance(value, str):
            return value[:2000]
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        if isinstance(value, dict):
            return {
                str(key)[:100]: cls._safe_event_value(item)
                for key, item in list(value.items())[:20]
            }
        if isinstance(value, (list, tuple)):
            return [cls._safe_event_value(item) for item in value[:20]]
        return str(value)[:2000]

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
