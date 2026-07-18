import asyncio
import json

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from app.agent.graph import AgentGraphFactory
from app.agent.model_factory import AgentModelBinding
from app.agent.schemas import AgentStreamRequest
from app.agent.service import AgentService
from app.agent.tools import registered_tools
from app.ai.models import AIRunMode, AIRunStatus
from app.conversations.models import MessageRole
from tests.test_ai_service import (
    FakeAIRunsRepository,
    FakeConversationService,
    make_principal,
)


class ToolCapableFakeModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class FakeAgentModelFactory:
    def __init__(self, model) -> None:
        self.model = model

    def create(self, requested=None) -> AgentModelBinding:
        return AgentModelBinding("deepseek", "deepseek-chat", self.model)


class BlockingGraph:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def astream_events(self, *args, **kwargs):
        self.started.set()
        await asyncio.Event().wait()
        yield {}


class BlockingGraphFactory:
    tool_names = ("calculate_business_metric",)

    def __init__(self, graph: BlockingGraph) -> None:
        self.graph = graph

    def create(self, model):
        return self.graph


def parse_event(frame: str) -> tuple[str, dict[str, object]]:
    lines = frame.strip().splitlines()
    return lines[0].removeprefix("event: "), json.loads(
        lines[1].removeprefix("data: ")
    )


async def prepare_service(model, *, recursion_limit: int = 8):
    principal = make_principal()
    runs = FakeAIRunsRepository()
    conversations = FakeConversationService(principal)
    service = AgentService(
        runs=runs,
        conversations=conversations,
        models=FakeAgentModelFactory(model),
        graphs=AgentGraphFactory(registered_tools()),
        history_limit=30,
        recursion_limit=recursion_limit,
    )
    request = AgentStreamRequest(
        conversation_id=conversations.conversation.id,
        message="请计算 12 * 8 + 4",
        provider="deepseek",
    )
    prepared = await service.prepare(principal, "agent-request-1", request)
    return service, principal, runs, conversations, prepared


async def test_agent_stream_emits_tool_events_and_persists_final_answer() -> None:
    model = ToolCapableFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "calculate_business_metric",
                        "args": {"expression": "12 * 8 + 4"},
                        "id": "agent-call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="计算结果是 100。"),
        ]
    )
    service, principal, runs, conversations, prepared = await prepare_service(model)
    events = [parse_event(frame) async for frame in service.stream(principal, prepared)]
    names = [name for name, _ in events]

    assert names[0] == "metadata"
    assert "tool_start" in names
    assert "tool_end" in names
    assert names[-1] == "message_end"
    assert [item.role for item in conversations.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]
    assert conversations.messages[-1].content == "计算结果是 100。"
    assert conversations.messages[-1].metadata["tool_call_count"] == 1
    run = runs.runs[prepared.execution.run.id]
    assert run.mode == AIRunMode.AGENT
    assert run.status == AIRunStatus.SUCCEEDED


async def test_agent_recursion_limit_emits_error_without_assistant_message() -> None:
    repeated_call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "calculate_business_metric",
                "args": {"expression": "1 + 1"},
                "id": "loop-call",
                "type": "tool_call",
            }
        ],
    )
    service, principal, runs, conversations, prepared = await prepare_service(
        ToolCapableFakeModel(responses=[repeated_call] * 10),
        recursion_limit=3,
    )
    events = [parse_event(frame) async for frame in service.stream(principal, prepared)]

    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "agent_recursion_limit"
    assert len(conversations.messages) == 1
    run = runs.runs[prepared.execution.run.id]
    assert run.status == AIRunStatus.FAILED


async def test_agent_cancellation_marks_run_cancelled() -> None:
    principal = make_principal()
    runs = FakeAIRunsRepository()
    conversations = FakeConversationService(principal)
    graph = BlockingGraph()
    service = AgentService(
        runs=runs,
        conversations=conversations,
        models=FakeAgentModelFactory(
            ToolCapableFakeModel(responses=[AIMessage(content="unused")])
        ),
        graphs=BlockingGraphFactory(graph),
        history_limit=30,
        recursion_limit=8,
    )
    request = AgentStreamRequest(
        conversation_id=conversations.conversation.id,
        message="等待",
    )
    prepared = await service.prepare(principal, "agent-cancel-1", request)
    stream = service.stream(principal, prepared)
    assert parse_event(await anext(stream))[0] == "metadata"

    pending = asyncio.create_task(anext(stream))
    await graph.started.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending

    assert len(conversations.messages) == 1
    run = runs.runs[prepared.execution.run.id]
    assert run.status == AIRunStatus.CANCELLED
