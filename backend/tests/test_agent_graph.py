import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from app.agent.graph import AgentGraphFactory
from app.agent.tools import registered_tools


class ToolCapableFakeModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


async def test_agent_graph_can_answer_without_tool() -> None:
    graph = AgentGraphFactory(registered_tools()).create(
        ToolCapableFakeModel(responses=[AIMessage(content="直接回答")])
    )
    result = await graph.ainvoke({"messages": [HumanMessage(content="你好")]})

    assert result["messages"][-1].content == "直接回答"
    assert not any(isinstance(item, ToolMessage) for item in result["messages"])


async def test_agent_graph_executes_tool_then_returns_final_answer() -> None:
    graph = AgentGraphFactory(registered_tools()).create(
        ToolCapableFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "calculate_business_metric",
                            "args": {"expression": "12 * 8 + 4"},
                            "id": "call-1",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="计算结果是 100。"),
            ]
        )
    )
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="计算 12 * 8 + 4")]}
    )

    tool_message = next(
        item for item in result["messages"] if isinstance(item, ToolMessage)
    )
    assert '"result":100' in tool_message.content
    assert result["messages"][-1].content == "计算结果是 100。"


async def test_agent_graph_converts_tool_failure_to_safe_tool_message() -> None:
    graph = AgentGraphFactory(registered_tools()).create(
        ToolCapableFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "calculate_business_metric",
                            "args": {"expression": "value.attribute"},
                            "id": "call-2",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="该表达式无法安全计算。"),
            ]
        )
    )
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="计算非法表达式")]}
    )

    tool_message = next(
        item for item in result["messages"] if isinstance(item, ToolMessage)
    )
    assert tool_message.status == "error"
    assert "工具执行失败" in tool_message.content
    assert result["messages"][-1].content == "该表达式无法安全计算。"


async def test_agent_graph_respects_recursion_limit() -> None:
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
    graph = AgentGraphFactory(registered_tools()).create(
        ToolCapableFakeModel(responses=[repeated_call] * 10)
    )

    with pytest.raises(GraphRecursionError):
        await graph.ainvoke(
            {"messages": [HumanMessage(content="持续计算")]},
            config={"recursion_limit": 3},
        )
